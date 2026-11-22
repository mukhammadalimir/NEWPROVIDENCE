@echo off
rem bkrs.info ma'nolarini oldindan o'zbekchaga tarjima qiladi (Gemini, bepul kalit),
rem keyin Mini App ma'lumotlarini (webapp\data) yangilaydi.
rem Eng ko'p ishlatiladigan so'zlardan boshlaydi. Bepul kalitning kunlik limiti tugasa
rem to'xtaydi - ertaga qayta ishga tushiring, tarjima qilinganlari saqlanib qoladi.
rem Mini App'da ko'rinishi uchun webapp\ o'zgarishlarini GitHub'ga (main) yuklash kerak.
chcp 65001 >nul
setlocal
cd /d "%~dp0backend"
if not exist ".venv\Scripts\python.exe" (
  echo [XATO] Avval ishga_tushirish.bat ni bir marta ishga tushiring.
  pause & exit /b 1
)
findstr /r /c:"^GEMINI_API_KEY=..*" ".env" >nul || (
  echo [XATO] backend\.env ichida GEMINI_API_KEY yo'q. Kalit: https://aistudio.google.com/apikey
  pause & exit /b 1
)
".venv\Scripts\python.exe" -m app.scripts.pretranslate_bkrs %*
echo.
echo Mini App ma'lumotlari yangilanmoqda...
".venv\Scripts\python.exe" -m app.scripts.export_offline --out ..\webapp\data
echo.
echo Tayyor. Mini App'da ko'rinishi uchun webapp\ ni GitHub'ga yuklang (main).
pause
