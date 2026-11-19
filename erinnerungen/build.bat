@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
set "MODE=%~1"
if "%MODE%"=="" set "MODE=all"

if /i "%MODE%"=="check"    goto :check
if /i "%MODE%"=="portable" goto :portable
if /i "%MODE%"=="linux"    goto :linux
if /i "%MODE%"=="android"  goto :android
if /i "%MODE%"=="all"      goto :all
echo usage: build.bat [all^|linux^|android^|portable^|check] & exit /b 1

:check
echo [build] python + unit tests + lint
where python >nul 2>nul || (echo [error] python missing — install Python 3.11+ & exit /b 1)
cd desktop
python -m pip install -q pytest ruff python-dateutil || exit /b 1
python -m pytest tests/ -q || exit /b 1
ruff check . || exit /b 1
cd ..
echo [build] prerequisites for the full build:
where java >nul 2>nul && (java -version 2>&1 | findstr /r "version") || echo [warn]  java missing — Android build needs JDK 17
if "%ANDROID_HOME%"=="" (echo [warn]  ANDROID_HOME not set — Android build needs the SDK) else echo [build] ANDROID_HOME=%ANDROID_HOME%
where wsl >nul 2>nul && echo [build] wsl found — Linux bundle will be built via WSL || echo [warn]  wsl missing — Linux bundle can only be built on Linux/WSL
goto :eof

:portable
echo [build] portable zipapp (works on any Linux with python3-gi/GTK4)
where python >nul 2>nul || (echo [error] python missing & exit /b 1)
rmdir /s /q desktop\build 2>nul
mkdir desktop\build\portable desktop\build\schemas
xcopy /e /i desktop\erinnerungen desktop\build\portable\erinnerungen >nul
python -m pip install -q --target desktop\build\portable python-dateutil || exit /b 1
copy desktop\data\*.gschema.xml desktop\build\schemas >nul
copy desktop\build\schemas\* desktop\build\portable\ >nul 2>nul
if not exist dist\linux mkdir dist\linux
python -m zipapp desktop\build\portable -o dist\linux\erinnerungen-1.0.0.pyz -p "/usr/bin/env python3" || exit /b 1
rmdir /s /q desktop\build
echo [build] portable OK -^> dist\linux\erinnerungen-1.0.0.pyz
goto :eof

:linux
where wsl >nul 2>nul || (echo [warn]  wsl not found — skipping Linux bundle; use 'portable' & exit /b 0)
wsl bash ./build.sh linux || exit /b 1
goto :eof

:android
where java >nul 2>nul || (echo [warn]  JDK 17 missing — skipping android & exit /b 0)
if "%ANDROID_HOME%"=="" (echo [warn]  ANDROID_HOME not set — skipping android & exit /b 0)
cd android
if exist gradlew.bat (set "GRADLE=gradlew.bat") else (where gradle >nul 2>nul && (set "GRADLE=gradle") || (echo [warn]  no gradle/gradlew — skipping android & exit /b 0))
echo [build] %GRADLE% :app:assembleRelease
%GRADLE% :app:assembleRelease || exit /b 1
cd ..
if not exist dist\android mkdir dist\android
copy /y android\app\build\outputs\apk\release\app-release.apk dist\android\erinnerungen-1.0.0.apk >nul
echo [build] android OK -^> dist\android\erinnerungen-1.0.0.apk
goto :eof

:all
call :check || exit /b 1
call :portable
call :linux
call :android
echo [build] done -^> artifacts in dist\
goto :eof
