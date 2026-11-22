@echo off
rem BKRSUZBOT - bepul rejimda o'z kompyuteringizda ishga tushirish.
rem Birinchi marta: hamma narsani o'rnatadi va lug'atni yuklaydi (10-15 daqiqa).
rem Keyingi safar: darhol botni ishga tushiradi. Bot to'xtab qolsa, o'zi qayta ishga tushadi.
chcp 65001 >nul
setlocal
cd /d "%~dp0backend"

rem --- 1. Python ---
set "PY="
where py >nul 2>nul && (py -3.12 --version >nul 2>nul && set "PY=py -3.12")
if not defined PY (where py >nul 2>nul && (py -3 --version >nul 2>nul && set "PY=py -3"))
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
  echo [XATO] Python topilmadi. https://www.python.org/downloads/ dan Python 3.12 o'rnating
  echo        ^(o'rnatishda "Add python.exe to PATH" belgisini qo'ying^).
  pause & exit /b 1
)

rem --- 2. Virtual muhit va kutubxonalar ---
if not exist ".venv\Scripts\python.exe" (
  echo [1/4] Python muhiti yaratilmoqda...
  %PY% -m venv .venv || (echo [XATO] venv yaratilmadi & pause & exit /b 1)
)
if not exist ".venv\.installed" (
  echo [2/4] Kutubxonalar o'rnatilmoqda...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip -q
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt -q || (echo [XATO] pip install & pause & exit /b 1)
  echo ok> ".venv\.installed"
)
set "VPY=%CD%\.venv\Scripts\python.exe"

rem --- 3. Sozlamalar (.env) ---
if not exist ".env" (
  copy /y "..\bepul.env.example" ".env" >nul
  echo.
  echo  backend\.env fayli yaratildi. Unga BOT_TOKEN va GEMINI_API_KEY ni yozing,
  echo  saqlang va ishga_tushirish.bat ni qaytadan oching.
  echo.
  start notepad ".env"
  pause & exit /b 0
)
findstr /r /c:"^BOT_TOKEN=..*" ".env" >nul || (
  echo [XATO] backend\.env ichida BOT_TOKEN bo'sh.
  start notepad ".env"
  pause & exit /b 1
)

rem --- 4. Baza va lug'at ---
"%VPY%" -m alembic upgrade head || (echo [XATO] baza yaratilmadi & pause & exit /b 1)
if not exist ".data_imported" (
  echo [3/4] CC-CEDICT lug'ati yuklanmoqda ^(bir marta, bir necha daqiqa^)...
  "%VPY%" -m app.scripts.import_cedict --url https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz || (echo [XATO] lug'at yuklanmadi & pause & exit /b 1)
  "%VPY%" -m app.scripts.seed
  "%VPY%" -m app.scripts.import_wikt --file ..\webapp\data\wikt.json
  echo ok> ".data_imported"
)
rem BKRS (bkrs.info): odamlar yozgan xitoycha-ruscha lug'at, ~90 MB, bir marta.
rem Yangilash uchun backend\.bkrs_imported faylini o'chirib, .bat ni qayta oching.
if not exist ".bkrs_imported" (
  echo [3/4] bkrs.info lug'ati yuklanmoqda ^(~90 MB, bir marta, 1-3 daqiqa^)...
  "%VPY%" -m app.scripts.import_bkrs && echo ok> ".bkrs_imported"
  if not exist ".bkrs_imported" echo [OGOHLANTIRISH] bkrs.info lug'ati yuklanmadi, bot CC-CEDICT bilan ishlaydi. Keyingi safar yana urinib ko'riladi.
)

rem --- 5. Bot ---
echo [4/4] Bot ishga tushdi. Bu oynani yopmang ^(yopsangiz bot to'xtaydi^).
:loop
"%VPY%" -m app.bot.main
echo.
echo Bot to'xtadi. 15 soniyadan keyin qayta ishga tushadi ^(Ctrl+C - butunlay to'xtatish^)...
timeout /t 15 /nobreak >nul
goto loop
