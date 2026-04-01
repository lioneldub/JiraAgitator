@echo off
REM lanceur simplifié pour JiraAgitator
REM Usage : launch_jira_simulator.bat [nombre_evenements]

set EVENTS=%1
if "%EVENTS%"=="" set EVENTS=10

REM active l'environnement virtuel (optionnel)
if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
)

echo Lancement de JiraAgitator avec %EVENTS% events...
python main.py --events %EVENTS%

if %ERRORLEVEL% neq 0 (
    echo Erreur durant l execution (code %ERRORLEVEL%).
    exit /b %ERRORLEVEL%
)

echo Terminé.
