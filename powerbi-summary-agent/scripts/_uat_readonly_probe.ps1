hostname

Get-Service -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Status -eq "Running" -and
        $_.Name -match "scanb|docker|retail|agent|iis|w3svc"
    } |
    Select-Object Name, DisplayName, Status |
    Format-Table -AutoSize

Get-ScheduledTask -ErrorAction SilentlyContinue |
    Where-Object { $_.TaskName -match "scanb|summary|agent|target|yoy|sb" } |
    Select-Object TaskName, TaskPath, State |
    Format-Table -AutoSize

Import-Module WebAdministration -ErrorAction SilentlyContinue
Get-Website -ErrorAction SilentlyContinue |
    Select-Object Name, State, PhysicalPath, Bindings |
    Format-List

Get-ChildItem -Path C:\inetpub\wwwroot,C:\apps,C:\services,C:\agents -Directory -Depth 3 -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match "scanb|powerbi|summary|agent|retail" } |
    Select-Object -First 50 -ExpandProperty FullName
