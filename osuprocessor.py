"""
Processes your osu! song library:

* Retrieves all osu! songs and copies them into a new folder
* Adds ID3-tags to the mp3s with the data provided by the beatmap

Run next to an Songs folder in your osu! folder
Also make a folder named "out" for the numbered files (00000.mp3 - 99999.mp3)

Requires eyed3: http://eyed3.nicfit.net/

Licensed under the MIT license
"""

import shutil
import eyed3 # tested on 0.7.5
import os
import re
from eyed3.id3 import Tag

path = "Songs/"
outpath = "out/"
counter = 0

for dirpath, dirs, files in os.walk(path):
	for name in files:
		if name.endswith((".mp3")):
			if len(name)>4:
				newname = outpath+("%05d"%counter)+".mp3"
				shutil.copyfile(os.path.join(dirpath, name), newname)
				counter+=1
				audiofile = eyed3.load(newname)
				if audiofile.tag is None:
					audiofile.initTag()
				if audiofile.info.time_secs > 10:
					for file in os.listdir(dirpath):
						if file.endswith(".osu"):
							with open(os.path.join(dirpath, file), "r") as osumeta:
								content = osumeta.read()
								title = unicode(re.search("Title:(.*)\n", content).group(1), "UTF-8")
								title = re.sub("\ \(tv\ size\)", "", title, flags=re.IGNORECASE)
								audiofile.tag.title = title
								artist = unicode(re.search("Artist:(.*)\n", content).group(1), "UTF-8")
								if (len(artist)>0):
									audiofile.tag.artist = artist
						audiofile.tag.save(version=eyed3.id3.ID3_V2_3)
					print audiofile.tag.title
				else:
					os.remove(newname)
					counter-=1
