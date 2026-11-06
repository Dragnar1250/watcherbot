@echo off
chcp 65001 >nul
cd /d "%~dp0"
title TurkBot
if not exist .venv (
  echo Ilk kurulum yapiliyor, biraz surebilir...
  py -3 -m venv .venv || python -m venv .venv
  call .venv\Scripts\activate.bat
  python -m pip install --upgrade pip
  pip install -r requirements.txt
) else (
  call .venv\Scripts\activate.bat
)
if not exist .env (
  copy .env.ornek .env >nul
  echo.
  echo .env dosyasi olusturuldu. Not Defteri ile acip DISCORD_TOKEN satirina tokenini yapistir, sonra bu dosyayi tekrar calistir.
  notepad .env
  pause
  exit /b
)
:dongu
python updater.py
python main.py
if %errorlevel% equ 2 (
  echo.
  echo Ayar hatasi var, yukaridaki mesaji oku. Duzelttikten sonra bu dosyayi tekrar calistir.
  pause
  exit /b
)
if %errorlevel% equ 3 (
  echo.
  echo Guncelleme icin yeniden baslatiliyor...
  goto dongu
)
echo.
echo Bot durdu. 5 saniye sonra yeniden baslatiliyor... (Kapatmak icin bu pencereyi kapat)
timeout /t 5 >nul
goto dongu
