# jsonc-sort-keys

A small tool to sort keys of a JSONC file in Unicode order

## Usage

```
usage: jsonc-sort-keys.py [-h] [--dump-syntax-tree] [--dangerous-overwrite-inplace | -o OUTPUT] [-p] input

A small tool to sort keys of a JSONC file in Unicode order

positional arguments:
  input                 input file path

options:
  -h, --help            show this help message and exit
  --dump-syntax-tree    Print the syntax tree instead of the JSONC file
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

This program tries to maintain the exact whitespace and formatting as the input file. Therefore, due to the reordering, you may need to use other tools (e.g., Zed) to reformat the file.

The program tolerates most syntax errors because it does not fully decode the JSON. You may use `--permissive` to tolerate *all* syntax errors. (In other words: This program almost has no error detection. If you feed it invalid input, you may get garbage output.)

## Disclaimer

I developed this tool because Zed cannot sort its own configuration file. I shared my code for the hope that it may benefit other people and it comes with absolutely no warranty. The software may contain bugs and may accidentally corrupt files. Please make backups of your files!

## Not vibe coded disclaimer

This tool is developed by human. However, if you want to see a version written by GPT-5.5, please check the [vibe-coded](https://codeberg.org/m13253/jsonc-sort-keys/src/branch/vibe-coded) branch.
