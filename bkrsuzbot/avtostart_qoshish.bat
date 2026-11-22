@echo off
rem Kompyuter yoqilganda bot o'zi ishga tushishi uchun "Startup" papkasiga yorliq qo'shadi.
rem Olib tashlash: Win+R -> shell:startup -> "BKRSUZBOT" yorlig'ini o'chiring.
chcp 65001 >nul
rem Yo'llar PowerShell'ga muhit o'zgaruvchisi orqali beriladi: papka nomida apostrof
rem (masalan C:\Users\O'tkir) bo'lsa ham buyruq buzilmaydi.
set "BK_TARGET=%~dp0ishga_tushirish.bat"
set "BK_DIR=%~dp0"
powershell -NoProfile -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup')+'\BKRSUZBOT.lnk');" ^
  "$s.TargetPath=$env:BK_TARGET; $s.WorkingDirectory=$env:BK_DIR; $s.WindowStyle=7; $s.Save()"
if errorlevel 1 (echo [XATO] yorliq yaratilmadi & pause & exit /b 1)
echo Tayyor: kompyuter yoqilganda bot avtomatik ishga tushadi ^(oyna kichraytirilgan holda^).
pause
