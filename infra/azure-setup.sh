#!/usr/bin/env bash
# One-time Azure setup for Assignment 2 (A2 §7, setup guide steps 1-9).
# After this, only the CD pipeline changes anything in Azure.
#
# Run in Azure Cloud Shell (Bash), which has az, gh and sqlcmd, signed in to
# the Azure for Students subscription. In zsh on a Mac, run `bash` first:
# zsh mangles "repo:$GH_REPO:ref:..." (setup guide, step 6).
#
#   export LOCATION=<one of your allowed regions>   # step 1 prints them
#   export SQL_LOCATION=<region for SQL>            # optional, if the free offer isn't in LOCATION
#   read -rs SQL_ADMIN_PASSWORD; export SQL_ADMIN_PASSWORD   # server admin, keep it in a password manager
#   gh auth login                                    # once, for the GitHub secrets in step 7
#   bash infra/azure-setup.sh
#
# Safe to re-run: anything that already exists is kept, not recreated.
#
# No password is written to a file or echoed. The two service passwords and
# TOKEN_SECRET are generated here and go straight into GitHub Actions secrets.
set -euo pipefail

PREFIX=glifshitz-ieu2024                 # IE username with . -> -
RG="rg-${PREFIX}"
STORAGE=glifshitzieu2024ui               # prefix without hyphens + ui
SQL_SERVER="${PREFIX}-sql"
ENVIRONMENT="${PREFIX}-env"
IDENTITY="${PREFIX}-github"
GH_REPO=G-Lifshitz/cybersec-roadmap
SERVICES=(roadmap progress)
: "${LOCATION:?set LOCATION to one of your allowed regions}"
SQL_LOCATION="${SQL_LOCATION:-$LOCATION}"
: "${SQL_ADMIN_PASSWORD:?set SQL_ADMIN_PASSWORD (read -rs SQL_ADMIN_PASSWORD)}"

step() { printf '\n== %s\n' "$*"; }
exists() { "$@" -o none >/dev/null 2>&1; }   # true if an `az ... show` finds the resource

# Cloud Shell doesn't always ship sqlcmd: fetch Microsoft's go-sqlcmd binary into ~/bin.
if ! command -v sqlcmd >/dev/null 2>&1; then
  mkdir -p "$HOME/bin"
  curl -sSL https://github.com/microsoft/go-sqlcmd/releases/latest/download/sqlcmd-linux-amd64.tar.bz2 \
    | tar -xj -C "$HOME/bin" sqlcmd
  export PATH="$HOME/bin:$PATH"
fi

# Letters and digits only (nothing to URL-encode in DATABASE_URL), with the
# upper/lower/digit mix Azure SQL's password policy wants.
gen_password() { echo "Aa1$(openssl rand -base64 48 | tr -dc 'A-Za-z0-9' | head -c 29)"; }

step "1. Subscription and allowed regions"
az account show --query "{subscription:name, id:id}" -o table
az policy assignment list \
  --query "[?contains(displayName, 'Allowed resource deployment regions')].parameters.listOfAllowedLocations.value | [0]" -o tsv

step "2. Providers and resource group"
for provider in Microsoft.App Microsoft.OperationalInsights Microsoft.Sql Microsoft.Storage Microsoft.ManagedIdentity; do
  az provider register --namespace "$provider" --wait
done
az group create --name "$RG" --location "$LOCATION" -o none
RG_ID=$(az group show --name "$RG" --query id -o tsv)

step "3. Storage account with static website (the UI)"
exists az storage account show --name "$STORAGE" --resource-group "$RG" ||
az storage account create --name "$STORAGE" --resource-group "$RG" --location "$LOCATION" \
  --sku Standard_LRS --kind StorageV2 --min-tls-version TLS1_2 -o none
az storage blob service-properties update --account-name "$STORAGE" --auth-mode key \
  --static-website --index-document index.html --404-document index.html -o none
UI_URL=$(az storage account show --name "$STORAGE" --resource-group "$RG" --query primaryEndpoints.web -o tsv)
UI_ORIGIN="${UI_URL%/}"
echo "UI: $UI_ORIGIN"

step "4. SQL server and one serverless database per service (free offer)"
exists az sql server show --name "$SQL_SERVER" --resource-group "$RG" ||
az sql server create --name "$SQL_SERVER" --resource-group "$RG" --location "$SQL_LOCATION" \
  --admin-user sqladmin --admin-password "$SQL_ADMIN_PASSWORD" --minimal-tls-version 1.2 -o none
# 0.0.0.0-0.0.0.0 is Azure's special rule for "allow Azure services".
az sql server firewall-rule create --resource-group "$RG" --server "$SQL_SERVER" \
  --name AllowAzureServices --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0 -o none
for svc in "${SERVICES[@]}"; do
  # The free offer fixes auto-pause (60 min) and max size (32 GB): don't pass them.
  exists az sql db show --resource-group "$RG" --server "$SQL_SERVER" --name "${PREFIX}-${svc}-db" ||
  az sql db create --resource-group "$RG" --server "$SQL_SERVER" --name "${PREFIX}-${svc}-db" \
    --edition GeneralPurpose --compute-model Serverless --family Gen5 \
    --min-capacity 0.5 --capacity 1 --backup-storage-redundancy Local \
    --use-free-limit true --free-limit-exhaustion-behavior AutoPause -o none
done

step "4b. One contained user per database (own database only, can run migrations)"
MY_IP=$(curl -s https://api.ipify.org)
az sql server firewall-rule create --resource-group "$RG" --server "$SQL_SERVER" \
  --name setup-ip --start-ip-address "$MY_IP" --end-ip-address "$MY_IP" -o none
declare -A DB_PASSWORDS
for svc in "${SERVICES[@]}"; do
  pw=$(gen_password)
  DB_PASSWORDS[$svc]=$pw
  sqlcmd -S "tcp:${SQL_SERVER}.database.windows.net,1433" -d "${PREFIX}-${svc}-db" \
    -U sqladmin -P "$SQL_ADMIN_PASSWORD" -b -Q "
      IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = '${svc}_svc')
          CREATE USER [${svc}_svc] WITH PASSWORD = N'${pw}';
      ELSE
          ALTER USER [${svc}_svc] WITH PASSWORD = N'${pw}';
      ALTER ROLE db_ddladmin ADD MEMBER [${svc}_svc];
      ALTER ROLE db_datareader ADD MEMBER [${svc}_svc];
      ALTER ROLE db_datawriter ADD MEMBER [${svc}_svc];"
done
# Close the firewall again (setup guide step 4).
az sql server firewall-rule delete --resource-group "$RG" --server "$SQL_SERVER" --name setup-ip -o none

step "5. Container Apps environment and one app per service"
az extension add --name containerapp --upgrade --yes -o none
# --logs-destination none: no Log Analytics workspace (an extra resource with
# its own billing). `az containerapp logs show --follow` still streams stdout.
exists az containerapp env show --name "$ENVIRONMENT" --resource-group "$RG" ||
az containerapp env create --name "$ENVIRONMENT" --resource-group "$RG" --location "$LOCATION" \
  --logs-destination none -o none
for svc in "${SERVICES[@]}"; do
  # Placeholder image; the first CD run replaces it and sets env vars and secrets.
  exists az containerapp show --name "${PREFIX}-${svc}" --resource-group "$RG" ||
  az containerapp create --name "${PREFIX}-${svc}" --resource-group "$RG" --environment "$ENVIRONMENT" \
    --image mcr.microsoft.com/k8se/quickstart:latest --ingress external --target-port 80 \
    --min-replicas 0 --max-replicas 1 --cpu 0.25 --memory 0.5Gi -o none
done

step "6. The pipeline's identity (OIDC, Contributor on this resource group only)"
az identity create --name "$IDENTITY" --resource-group "$RG" --location "$LOCATION" -o none
CLIENT_ID=$(az identity show --name "$IDENTITY" --resource-group "$RG" --query clientId -o tsv)
PRINCIPAL_ID=$(az identity show --name "$IDENTITY" --resource-group "$RG" --query principalId -o tsv)
[ -n "$(az role assignment list --assignee "$PRINCIPAL_ID" --role Contributor --scope "$RG_ID" --query "[0].id" -o tsv)" ] ||
az role assignment create --assignee-object-id "$PRINCIPAL_ID" --assignee-principal-type ServicePrincipal \
  --role Contributor --scope "$RG_ID" -o none
# GitHub may send the subject with names or with numeric IDs; register both.
OWNER_ID=$(gh api "repos/${GH_REPO}" --jq .owner.id)
REPO_ID=$(gh api "repos/${GH_REPO}" --jq .id)
exists az identity federated-credential show --name github-main --identity-name "$IDENTITY" --resource-group "$RG" ||
az identity federated-credential create --name github-main --identity-name "$IDENTITY" --resource-group "$RG" \
  --issuer https://token.actions.githubusercontent.com --audiences api://AzureADTokenExchange \
  --subject "repo:${GH_REPO}:ref:refs/heads/main" -o none
exists az identity federated-credential show --name github-main-ids --identity-name "$IDENTITY" --resource-group "$RG" ||
az identity federated-credential create --name github-main-ids --identity-name "$IDENTITY" --resource-group "$RG" \
  --issuer https://token.actions.githubusercontent.com --audiences api://AzureADTokenExchange \
  --subject "repo:${GH_REPO%%/*}@${OWNER_ID}/${GH_REPO##*/}@${REPO_ID}:ref:refs/heads/main" -o none
az identity federated-credential list --identity-name "$IDENTITY" --resource-group "$RG" --query "[].subject" -o tsv

step "7. GitHub Actions secrets and variables"
gh secret set AZURE_CLIENT_ID       -R "$GH_REPO" --body "$CLIENT_ID"
gh secret set AZURE_TENANT_ID       -R "$GH_REPO" --body "$(az account show --query tenantId -o tsv)"
gh secret set AZURE_SUBSCRIPTION_ID -R "$GH_REPO" --body "$(az account show --query id -o tsv)"
gh secret set ROADMAP_DB_PASSWORD   -R "$GH_REPO" --body "${DB_PASSWORDS[roadmap]}"
gh secret set PROGRESS_DB_PASSWORD  -R "$GH_REPO" --body "${DB_PASSWORDS[progress]}"
gh secret set TOKEN_SECRET          -R "$GH_REPO" --body "$(openssl rand -hex 32)"
gh variable set PREFIX         -R "$GH_REPO" --body "$PREFIX"
gh variable set RESOURCE_GROUP -R "$GH_REPO" --body "$RG"
gh variable set UI_STORAGE     -R "$GH_REPO" --body "$STORAGE"
gh variable set UI_ORIGIN      -R "$GH_REPO" --body "$UI_ORIGIN"
gh variable set SQL_SERVER     -R "$GH_REPO" --body "$SQL_SERVER"
unset DB_PASSWORDS

step "9. Reader role for the professors"
for prof in amartini@faculty.ie.edu bserra@faculty.ie.edu; do
  az role assignment create --assignee "$prof" --role Reader --scope "$RG_ID" -o none \
    || echo "Could not add $prof (not in this directory?): ask the professor how to invite them."
done

step "Done"
az resource list --resource-group "$RG" --query "[].{name:name, type:type}" -o table
echo "Public URL: $UI_ORIGIN"
