Installation
---------------

Download requirements using the command:
pip install -r ./requirements.txt


Usage
--------------

The source file, main.py, can be run on Python 3.10, and similar versions should theoretically also function, albeit untested.

Alternatively, if you are using a Windows machine, run main.exe.


Configuration
-----------------------

The configuration file, config.txt, must be placed within this directory. 

Of these options, one might find it useful to alter:
- the song directory (songdir) where songs are automatically stored and looked for,
- the download directory (downloaddir) storing temporary download files,
- and the option "folders" which specifies the folders appearing in the file dialog within the program: one can add paths separated with ';'. 

It is not recommended to alter other options in the configuration file.
