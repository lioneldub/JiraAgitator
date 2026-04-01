# Lanceur PowerShell pour JiraAgitator
# Usage : .\launch_jira_simulator.ps1 [-Events 10]
param(
    [int]$Events = 10
)

$venvActivate = Join-Path $PSScriptRoot '.venv\Scripts\Activate.ps1'
if (Test-Path $venvActivate) {
    Write-Host "Activation de l'environnement virtuel .venv..."
    . $venvActivate
}

Write-Host "Lancement de JiraAgitator avec $Events événements..."
$proc = Start-Process -FilePath 'python' -ArgumentList "main.py --events $Events" -NoNewWindow -Wait -PassThru
if ($proc.ExitCode -ne 0) {
    Write-Error "Erreur durant l'exécution (code $($proc.ExitCode))."
    exit $proc.ExitCode
}

Write-Host 'Terminé.'
