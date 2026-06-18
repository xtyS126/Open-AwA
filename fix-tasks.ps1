$f = 'd:\代码\Open-AwA\.trae\specs\enhance-human-computer-collaboration\tasks.md'
$c = [System.IO.File]::ReadAllText($f, [System.Text.Encoding]::UTF8)
$c = $c.Replace('- [ ] Task 9', '- [x] Task 9').Replace('- [ ] 9.', '- [x] 9.')
[System.IO.File]::WriteAllText($f, $c, [System.Text.Encoding]::UTF8)
Write-Host "Done"
