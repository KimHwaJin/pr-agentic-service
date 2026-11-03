# Run the service over https on a dev PC to try the SSO login.
#
# The SSO cookie only reaches hosts under the IdP domain, and
# that domain forces https (HSTS). So:
#   1. hosts file (as admin): 127.0.0.1  dtest-local.<idp domain>
#   2. .env:
#        SSO_ADAPTER=idp
#        PUBLIC_API_ORIGIN=https://dtest-local.<idp domain>:5000
#        FRONTEND_ORIGIN=https://dtest-local.<idp domain>:5000
#        SSO_ALLOWED_RETURN_ROOTS=["/", "/dev"]
#        SSO_ALLOWED_ORIGINS=["<origin from the sso_login_url_rejected log>"]
#        COOKIE_SECURE=true
#   3. From the repo root:
#        .\scripts\run_local_https.ps1 -HostName dtest-local.<idp domain>
#   4. Open https://<HostName>:<Port>/api/v1/auth/login/sso?return_to=/dev/
#      and accept the certificate warning once.
#
# With the gaia template (src/gaia/core.py) it runs app.py, so /docs has
# the template's APIs too; gaia's main() takes no TLS options, so
# scripts/run_app_tls.py adds them, and the port is gaia's config.PORT
# (-Port is ignored). Without gaia (main, or -NoGaia) it runs uvicorn
# directly on -Port. Make a new certificate with -NewCert.

param(
    [Parameter(Mandatory = $true)][string]$HostName,
    [int]$Port = 5000,
    [switch]$NewCert,
    [switch]$NoGaia
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$key = Join-Path $root ".local\tls\$HostName-key.pem"
$cert = Join-Path $root ".local\tls\$HostName-cert.pem"
if ($NewCert -or -not (Test-Path $key) -or -not (Test-Path $cert)) {
    uv run --with cryptography python scripts/make_local_cert.py $HostName
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

# Same interpreter as `uv run python`: print it so a wrong environment
# shows up before the app fails on an import.
uv run python -c "import sys, pgvector; print('python:', sys.executable)"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# The gaia template's app.py: its routers and ours, as in the company network.
if (-not $NoGaia -and (Test-Path (Join-Path $root "src\gaia\core.py"))) {
    Write-Host "gaia app.py (port: gaia config.PORT)"
    uv run python scripts/run_app_tls.py $key $cert
    exit $LASTEXITCODE
}

# internal/gaia keeps the app in src/dtest; main runs src/main.py.
Write-Host "without gaia: our routes only"
if (Test-Path (Join-Path $root "src\dtest\local.py")) {
    $app = @("src.dtest.local:app")
} else {
    $app = @("main:app", "--app-dir", "src")
}

# psycopg async needs the selector loop on Windows.
uv run python -m uvicorn @app --host 0.0.0.0 --port $Port `
    --loop asyncio:SelectorEventLoop `
    --ssl-keyfile $key --ssl-certfile $cert
