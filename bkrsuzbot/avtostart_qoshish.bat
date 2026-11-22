@echo off
rem Kompyuter yoqilganda bot o'zi ishga tushishi uchun "Startup" papkasiga yorliq qo'shadi.
rem Olib tashlash: Win+R -> shell:startup -> "BKRSUZBOT" yorlig'ini o'chiring.
chcp 65001 >nul
set "TARGET=%~dp0ishga_tushirish.bat"
powershell -NoProfile -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup')+'\BKRSUZBOT.lnk');" ^
  "$s.TargetPath='%TARGET%'; $s.WorkingDirectory='%~dp0'; $s.WindowStyle=7; $s.Save()"
if errorlevel 1 (echo [XATO] yorliq yaratilmadi & pause & exit /b 1)
echo Tayyor: kompyuter yoqilganda bot avtomatik ishga tushadi ^(oyna kichraytirilgan holda^).
pause
