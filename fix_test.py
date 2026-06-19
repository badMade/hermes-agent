import subprocess
print(subprocess.run("cat", shell=True, input=b"hello"))
