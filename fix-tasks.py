import pathlib

f = pathlib.Path(r'd:\代码\Open-AwA\.trae\specs\enhance-human-computer-collaboration\tasks.md')
c = f.read_text(encoding='utf-8')
c = c.replace('- [ ] Task 9', '- [x] Task 9').replace('- [ ] 9.', '- [x] 9.')
f.write_text(c, encoding='utf-8')
print("Done")
