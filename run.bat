@echo off
echo ===================================================
echo   Social Media Animation Generator Setup ^& Launch
echo ===================================================

:: Try to find a working Python command in PATH
set PYTHON_CMD=python
python --version >nul 2>&1
if not errorlevel 1 goto PYTHON_FOUND

set PYTHON_CMD=py
py --version >nul 2>&1
if not errorlevel 1 goto PYTHON_FOUND

set PYTHON_CMD=python3
python3 --version >nul 2>&1
if not errorlevel 1 goto PYTHON_FOUND

goto NO_PYTHON

:PYTHON_FOUND
echo Found working Python command: %PYTHON_CMD%

:: Create Virtual Environment if not exists
if exist venv\Scripts\python.exe goto VENV_EXISTS

echo Creating python virtual environment (venv)...
%PYTHON_CMD% -m venv venv
if errorlevel 1 goto VENV_FAIL

:VENV_EXISTS
:: Install/Upgrade dependencies using venv Python directly
echo Upgrading pip...
venv\Scripts\python.exe -m pip install --upgrade pip --quiet
if errorlevel 1 goto PIP_FAIL

echo Installing requirements from requirements.txt...
venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto REQ_FAIL

:: Ensure app directories exist
if not exist app mkdir app
if not exist app\static mkdir app\static

:: Launch FastAPI Server
echo Starting the web app and opening dashboard...
start http://localhost:8000
venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
goto END

:NO_PYTHON
echo [ERROR] Python is not installed or not in your system PATH.
echo Please install Python 3.10+ and make sure to check the
echo "Add Python to PATH" box during installation.
echo.
echo You can download Python from: https://www.python.org/downloads/
echo.
pause
exit /b 1

:VENV_FAIL
echo [ERROR] Failed to create virtual environment using: %PYTHON_CMD% -m venv venv
echo Please verify that your Python installation is complete and has venv module installed.
pause
exit /b 1

:PIP_FAIL
echo [ERROR] Failed to upgrade pip in virtual environment.
pause
exit /b 1

:REQ_FAIL
echo [ERROR] Failed to install package requirements.
echo Please check your internet connection and verify that pip works.
pause
exit /b 1

:END
pause
