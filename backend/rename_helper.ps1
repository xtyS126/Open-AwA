try {
    Rename-Item -Path 'd:\代码\Open-AwA\backend\migrations\add_memory_layers.py' -NewName 'add_memory_layers.py.bak' -ErrorAction Stop
    Write-Output 'Rename OK'
} catch {
    Write-Output ('Error: ' + $_.Exception.Message)
}
