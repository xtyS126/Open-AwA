$filePath = 'd:\代码\Open-AwA\backend\migrations\add_memory_layers.py'
takeown /f $filePath 2>&1 | Out-Null
icacls $filePath /grant "$env:USERNAME:(F)" 2>&1 | Out-Null
$result = Test-Path $filePath
Set-Content -Path 'd:\代码\Open-AwA\backend\perm_granted.txt' -Value "done:$result"
