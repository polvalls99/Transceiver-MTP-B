# Transceiver-MTP-B

## How to launch transmission in both raspberries:

Simply running the following script:

```
./load_and_run_yml.py
```

This script synchronizes the contents of the local repository 
in the raspberries, and runs the desired program.

Once the command finishes, all the files generated under the
`results` directory are copied back into your computer.

The idea behind this python script is that it is cross-platform,
this way we do not depend as much in windows.

All the basic configurations can be done inside `config.yml`,
but feel free to add more parameters if you want.

