#!/bin/bash

# Script to split super.img into 800MB chunks

FILE_TO_SPLIT="build/baserom/images/super.img"
CHUNK_SIZE="800M"

if [ -f "$FILE_TO_SPLIT" ]; then
    echo "Splitting $FILE_TO_SPLIT into $CHUNK_SIZE chunks..."
    # -b 800M: split by 800MB
    # -d: use numeric suffixes (00, 01, 02) instead of letters (aa, ab)
    # The output will be super.img.00, super.img.01, etc.
    split -b "$CHUNK_SIZE" -d "$FILE_TO_SPLIT" "$FILE_TO_SPLIT."
    
    echo "Done! Parts created:"
    ls -lh ${FILE_TO_SPLIT}.*
else
    echo "Error: $FILE_TO_SPLIT not found."
    echo "Please run this script after super.img is packed."
    exit 1
fi
