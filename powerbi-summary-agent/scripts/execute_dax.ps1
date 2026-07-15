param(
    [string]$OutputFolder = "outputs"
)

# ---------------------------------------------------------------------------
# execute_dax.ps1  (Node 7, execution_mode = "powershell")
#
# Reads outputs/validated_dax_queries.json + outputs/_ps_exec_config.json,
# runs each valid DAX query one at a time via the Power BI REST executeQueries
# endpoint, and writes outputs/raw_pbi_results.json in the same shape the
# Python executor produces, so the normalizer works for both paths.
#
# Run visibly from a normal terminal (interactive login works there):
#   powershell -ExecutionPolicy Bypass -File scripts/execute_dax.ps1
# ---------------------------------------------------------------------------

$ErrorActionPreference = "Stop"

Import-Module MicrosoftPowerBIMgmt.Profile -Force

# Ensure we have a session (interactive login if needed - browser will appear).
try {
    $null = Get-PowerBIAccessToken
} catch {
    Connect-PowerBIServiceAccount | Out-Null
}

$root = Split-Path -Parent $PSScriptRoot
$outDir = Join-Path $root $OutputFolder
$cfg = Get-Content (Join-Path $outDir "_ps_exec_config.json") -Raw | ConvertFrom-Json
$queries = Get-Content (Join-Path $outDir "validated_dax_queries.json") -Raw | ConvertFrom-Json

$workspaceId = $cfg.workspace_id
$datasetId = $cfg.dataset_id
$results = [ordered]@{}
$log = @()

foreach ($q in $queries) {
    if ($q.status -and $q.status -ne "valid") { continue }
    $name = $q.name
    $body = @{
        queries = @(@{ query = $q.dax })
        serializerSettings = @{ includeNulls = $true }
    } | ConvertTo-Json -Depth 6

    $url = "groups/$workspaceId/datasets/$datasetId/executeQueries"
    try {
        $resp = Invoke-PowerBIRestMethod -Url $url -Method Post -Body $body
        $results[$name] = @{
            status  = "success"
            purpose = $q.purpose
            query   = $q.dax
            result  = ($resp | ConvertFrom-Json)
        }
        $log += "[ok] $name"
    } catch {
        $results[$name] = @{
            status  = "failed"
            purpose = $q.purpose
            query   = $q.dax
            error   = $_.Exception.Message
        }
        $log += "[fail] $name : $($_.Exception.Message)"
    }
}

$results | ConvertTo-Json -Depth 12 | Set-Content (Join-Path $outDir "raw_pbi_results.json") -Encoding UTF8
$log | Set-Content (Join-Path $outDir "run_log.txt") -Encoding UTF8
Write-Output "execute_dax.ps1 done: $($results.Count) queries."
