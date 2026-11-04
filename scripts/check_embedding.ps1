# Check the embedding gateway (EMBEDDING_PROVIDER=openai) from Windows.
# PowerShell version of scripts/check_embedding.sh (Windows PowerShell 5.1
# and PowerShell 7).
#
# The service calls it through langchain_openai.OpenAIEmbeddings, which posts
#   {"model": ..., "input": [..], "dimensions": EMBEDDING_DIMS,
#    "encoding_format": "base64"}
# to $EMBEDDING_BASE_URL/embeddings. Each case below adds one of those fields
# to a minimal request, so the first failing case names the field the gateway
# rejects. The JSON is built by ConvertTo-Json and sent as UTF-8 bytes, so
# cmd/PowerShell quoting cannot break it (curl -d '...' in cmd sends the
# quotes literally and the gateway answers "Missing required parameter:
# 'input'").
#
# From the repo root:
#   powershell -ExecutionPolicy Bypass -File scripts\check_embedding.ps1 `
#     -BaseUrl http://model.frodo.com/v1 -Model bge-m3 -ApiKey <key> -Dims 1024
# Parameters left out come from the EMBEDDING_* environment variables.

param(
    [string]$BaseUrl = $env:EMBEDDING_BASE_URL,
    [string]$Model = $env:EMBEDDING_MODEL,
    [string]$ApiKey = $(if ($env:EMBEDDING_API_KEY) { $env:EMBEDDING_API_KEY } else { "EMPTY" }),
    [int]$Dims = $(if ($env:EMBEDDING_DIMS) { [int]$env:EMBEDDING_DIMS } else { 1024 }),
    [string]$Text = "매출 추이 분석"
)

if (-not $BaseUrl -or -not $Model) {
    Write-Error "Give -BaseUrl (up to /v1) and -Model, or set EMBEDDING_BASE_URL and EMBEDDING_MODEL"
    exit 1
}

$Url = $BaseUrl.TrimEnd("/") + "/embeddings"
$Headers = @{ Authorization = "Bearer $ApiKey" }

function Invoke-Case([string]$Name, $Body) {
    $json = $Body | ConvertTo-Json -Compress -Depth 5
    Write-Host "=== $Name"
    Write-Host "    body: $json"
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    $status = 0
    $content = ""
    try {
        $resp = Invoke-WebRequest -Uri $Url -Method Post -Headers $Headers `
            -ContentType "application/json; charset=utf-8" -Body $bytes `
            -UseBasicParsing -TimeoutSec 60
        $status = [int]$resp.StatusCode
        $content = $resp.Content
    } catch {
        $r = $_.Exception.Response
        if ($r) { $status = [int]$r.StatusCode }
        if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
            $content = $_.ErrorDetails.Message  # PowerShell 7
        } elseif ($r -and ($r -is [System.Net.WebResponse])) {
            $reader = New-Object System.IO.StreamReader($r.GetResponseStream())
            $content = $reader.ReadToEnd()  # Windows PowerShell 5.1
        } else {
            $content = $_.Exception.Message  # no response: DNS, refused, timeout
        }
    }
    Write-Host "    HTTP $status"
    if ($status -eq 200) {
        try {
            $emb = ($content | ConvertFrom-Json).data[0].embedding
            if ($emb -is [string]) {
                $n = [System.Convert]::FromBase64String($emb).Length / 4
                Write-Host "    base64 embedding, $n dims"
            } else {
                Write-Host "    float embedding, $($emb.Count) dims"
            }
        } catch {
            Write-Host "    200 but not an embeddings response:"
            Write-Host ("    " + $content.Substring(0, [Math]::Min(400, $content.Length)))
        }
    } else {
        Write-Host ("    " + $content.Substring(0, [Math]::Min(400, $content.Length)))
    }
}

Write-Host "POST $Url (model=$Model, dims=$Dims)"
Invoke-Case "1 minimal, input string" `
    ([ordered]@{ model = $Model; input = $Text })
Invoke-Case "2 input array (the service always sends an array)" `
    ([ordered]@{ model = $Model; input = @($Text) })
Invoke-Case "3 + dimensions" `
    ([ordered]@{ model = $Model; input = @($Text); dimensions = $Dims })
Invoke-Case "4 exactly what the service sends (+ encoding_format base64)" `
    ([ordered]@{ model = $Model; input = @($Text); dimensions = $Dims; encoding_format = "base64" })
Write-Host ""
Write-Host "The embedding length must equal EMBEDDING_DIMS ($Dims) for pgvector search."
