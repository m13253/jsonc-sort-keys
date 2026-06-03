# jsonc-sort-keys

A small tool to sort keys of a JSONC file in Unicode order

## Usage

```
usage: jsonc-sort-keys.py [-h] [--dangerous-overwrite-inplace | -o OUTPUT] [-p] input

A small tool to sort keys of a JSONC file in Unicode order

positional arguments:
  input                 input file path

options:
  -h, --help            show this help message and exit
  --dangerous-overwrite-inplace
                        Dangerous: overwrite the input file in place
  -o, --output OUTPUT   output file path
  -p, --permissive      tolerate all syntax errors and try to fix them at best effort
```

This tool transforms your JSONC from:
```jsonc
{
    // Comments before b
    "b": 2, // Inline comments after b
    // Comments before a
    "a": 1  // Inline comments after a
}
```
into:
```jsonc
{
    // Comments before a
    "a": 1,  // Inline comments after a
    // Comments before b
    "b": 2 // Inline comments after b
}
```

This program tries to maintain the exact whitespace and formatting as the input file. Therefore, after the transformation, you may need to use other tools (e.g., Zed) to reformat the file.

The program tolerates most syntax errors because it does not fully decode the JSON. You may use `--permissive` to tolerate *all* syntax errors. (In other words: This program has very poor error detection. If you feed it invalid input, you may get garbage output.)

## Disclaimer

I developed this tool because Zed cannot sort its own configuration file. I shared my code for the hope that it may benefit other people and it comes with absolutely no warranty. The software may contain bugs and may accidentally corrupt files. Please make backups of your files!
