import urllib.request
import json
import os

url = "https://api.github.com/repos/NousResearch/hermes-agent/pulls/1/reviews"
req = urllib.request.Request(url)
try:
    with urllib.request.urlopen(req) as response:
        print(response.read().decode())
except Exception as e:
    print(f"Error: {e}")
