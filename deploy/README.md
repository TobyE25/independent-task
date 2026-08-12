# Deploying to Google Cloud

The exact commands, in order. Everything is regional to **europe-west2 (London)** — a UK retailer's
customer data stays in-region, which is a data residency decision rather than a latency one, and it
has to be set at creation because a bucket's and a BigQuery dataset's location cannot be changed
afterwards.

Orchestration is **Cloud Workflows + Cloud Run Jobs + Cloud Scheduler**, not Composer — see
DECISIONS.md D9 for why, and DESIGN.md §2 for the Airflow equivalent as pseudocode.

```bash
export PROJECT=sprouts-pizza-perfect
export REGION=europe-west2
export BUCKET_LANDING=${PROJECT}-landing
export BUCKET_LAKE=${PROJECT}-lake
```

## 1. Storage

```bash
# Landing: where the ecommerce platform drops exports. The pipeline needs read-only here.
gcloud storage buckets create gs://$BUCKET_LANDING --location=$REGION \
    --uniform-bucket-level-access --public-access-prevention

# The lake: bronze (immutable raw) + silver (Parquet).
gcloud storage buckets create gs://$BUCKET_LAKE --location=$REGION \
    --uniform-bucket-level-access --public-access-prevention
```

Uniform bucket-level access turns off per-object ACLs, so access is governed by IAM alone — one place
to reason about instead of two. Public access prevention makes an accidentally-public bucket
impossible rather than merely unlikely.

**The 30-day expiry on raw is a GDPR control, not housekeeping** (D6): raw carries the email
addresses and full postcodes that the privacy layer strips, so storage limitation (Art. 5(1)(e))
means it must not live forever. It is also what keeps an erasure request confined to one zone.

```bash
cat > /tmp/lifecycle.json <<'JSON'
{"rule": [
  {"action": {"type": "Delete"},
   "condition": {"age": 30, "matchesPrefix": ["bronze/"]}}
]}
JSON
gcloud storage buckets update gs://$BUCKET_LAKE --lifecycle-file=/tmp/lifecycle.json
```

## 2. The pseudonymisation key

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))" | \
  gcloud secrets create pizza-perfect-pseudonym-key --data-file=- \
    --replication-policy=user-managed --locations=$REGION
```

This key is what makes customer pseudonyms infeasible to reverse (D5). It is never in an image, a
config file or an environment file — Cloud Run mounts it at runtime, and `config.py` refuses to start
without it, so a misconfigured deployment fails immediately instead of emitting predictable
pseudonyms that look perfectly correct.

## 3. Service accounts — one per job, least privilege

```bash
for job in ingest-sports ingest-sales register dbt reconcile; do
  gcloud iam service-accounts create pp-$job --display-name="Pizza Perfect: $job"
done
```

A separate identity per step so a compromise of one is not a compromise of all. The ones worth
noting:

```bash
# Sales ingestion: READ the landing bucket, WRITE the lake. No delete anywhere — the pipeline has no
# legitimate reason to remove a source file, so it should not be able to.
gcloud storage buckets add-iam-policy-binding gs://$BUCKET_LANDING \
    --member=serviceAccount:pp-ingest-sales@$PROJECT.iam.gserviceaccount.com \
    --role=roles/storage.objectViewer
gcloud storage buckets add-iam-policy-binding gs://$BUCKET_LAKE \
    --member=serviceAccount:pp-ingest-sales@$PROJECT.iam.gserviceaccount.com \
    --role=roles/storage.objectCreator

# Only the sales job can read the pseudonymisation key. Nothing else needs it.
gcloud secrets add-iam-policy-binding pizza-perfect-pseudonym-key \
    --member=serviceAccount:pp-ingest-sales@$PROJECT.iam.gserviceaccount.com \
    --role=roles/secretmanager.secretAccessor
```

No service-account key files anywhere. Cloud Run uses the attached identity, and a key that does not
exist cannot leak, expire or need rotating.

## 4. Build the image

```bash
gcloud builds submit --tag $REGION-docker.pkg.dev/$PROJECT/pizza-perfect/pipeline:latest ..
```

## 5. The jobs

One image, five jobs, each overriding the command. One artefact to build, scan and promote.

```bash
IMAGE=$REGION-docker.pkg.dev/$PROJECT/pizza-perfect/pipeline:latest
COMMON="--region=$REGION --image=$IMAGE \
  --set-env-vars=TARGET=gcp,GCP_PROJECT=$PROJECT,GCP_LOCATION=$REGION,\
BUCKET_LANDING=$BUCKET_LANDING,BUCKET_LAKE=$BUCKET_LAKE"

# Sports: one task. It is rate-limited, so parallelism would only produce 429s.
gcloud run jobs create pizza-perfect-ingest-sports $COMMON \
    --service-account=pp-ingest-sports@$PROJECT.iam.gserviceaccount.com \
    --tasks=1 --task-timeout=30m --max-retries=2

# Sales: 8 parallel tasks. This is the Cloud Run equivalent of Airflow's dynamic task mapping —
# each container reads CLOUD_RUN_TASK_INDEX and takes every 8th export (D10). Estimated ~304 files
# and ~3M rows at the forecast peak, so 8 shards is comfortable headroom.
gcloud run jobs create pizza-perfect-ingest-sales $COMMON \
    --service-account=pp-ingest-sales@$PROJECT.iam.gserviceaccount.com \
    --set-secrets=PSEUDONYM_HMAC_KEY=pizza-perfect-pseudonym-key:latest \
    --tasks=8 --parallelism=8 --task-timeout=30m --max-retries=3 --memory=512Mi

gcloud run jobs create pizza-perfect-register $COMMON \
    --service-account=pp-register@$PROJECT.iam.gserviceaccount.com --args=register

gcloud run jobs create pizza-perfect-dbt $COMMON \
    --service-account=pp-dbt@$PROJECT.iam.gserviceaccount.com \
    --command=dbt --task-timeout=30m

gcloud run jobs create pizza-perfect-reconcile $COMMON \
    --service-account=pp-reconcile@$PROJECT.iam.gserviceaccount.com \
    --set-secrets=PSEUDONYM_HMAC_KEY=pizza-perfect-pseudonym-key:latest \
    --args=reconcile
```

512Mi on the sales job is deliberate headroom: the CSV is read in batches (D13), so memory is a function
of batch size rather than file count and should stay flat in the tens of MB. The exact ceiling wants
confirming on a real run before anyone tightens it.

## 6. Orchestrate and schedule

```bash
gcloud workflows deploy pizza-perfect-daily --source=workflow.yaml \
    --location=$REGION --service-account=pp-workflow@$PROJECT.iam.gserviceaccount.com

# 08:15 Europe/London, after the 05:00-08:00 export window. Local time, not UTC: the window is a
# business-hours promise, so a UTC schedule would drift an hour twice a year and start missing files
# every summer.
gcloud scheduler jobs create http pizza-perfect-daily \
    --schedule="15 8 * * *" --time-zone="Europe/London" --location=$REGION \
    --uri="https://workflowexecutions.googleapis.com/v1/projects/$PROJECT/locations/$REGION/workflows/pizza-perfect-daily/executions" \
    --oauth-service-account-email=pp-scheduler@$PROJECT.iam.gserviceaccount.com
```

## 7. Backfill

A parameter, not a code change — the same reason dbt takes `as_of_date` as a var:

```bash
gcloud workflows run pizza-perfect-daily --location=$REGION \
    --data='{"logical_date":"2026-08-14","sales_shards":16}'
```

## Teardown

```bash
gcloud projects delete $PROJECT
```

Worth doing via a dedicated project: one command removes everything, with nothing stranded and
still billing.

---

## What is deliberately not here

Named rather than left as gaps:

- **Terraform.** These commands should be IaC before anyone relies on them; `gcloud` is fine for
  demonstrating the shape and wrong for managing it. This is the first thing I would convert.
- **VPC Service Controls.** A perimeter around the lake and BigQuery would prevent data leaving via
  a compromised identity. Worth it for real customer data; over-engineering for an assessment.
- **CMEK.** Google-managed encryption is on by default. Customer-managed keys add key rotation
  control and an audit trail, and are usually a compliance requirement rather than a security one.
- **Monitoring and alerting.** Freshness SLO on the mart, an alert on the quarantine rate (the
  metric that catches an upstream schema change), and row-count anomaly detection. The pipeline
  emits the numbers; nothing yet watches them.
