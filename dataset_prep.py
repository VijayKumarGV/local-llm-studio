"""
Dataset preparation utility for LLM fine-tuning.
Validates JSONL format, checks message structure, and splits datasets for training.
"""

import json
import sys
import os

def validate_and_inspect(file_path: str):
    if not os.path.exists(file_path):
        print(f"[-] File not found: {file_path}")
        return False

    valid_count = 0
    errors = []

    with open(file_path, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                if "messages" not in item:
                    errors.append(f"Line {idx}: Missing 'messages' key")
                    continue
                msgs = item["messages"]
                if not isinstance(msgs, list) or len(msgs) < 2:
                    errors.append(f"Line {idx}: 'messages' must be a list with at least 2 entries (user & assistant)")
                    continue
                valid_count += 1
            except json.JSONDecodeError as e:
                errors.append(f"Line {idx}: Invalid JSON syntax - {e}")

    print(f"[*] Inspected: {file_path}")
    print(f"[+] Valid training samples: {valid_count}")
    if errors:
        print(f"[-] Found {len(errors)} issues:")
        for err in errors[:5]:
            print(f"    - {err}")
        if len(errors) > 5:
            print(f"    ... and {len(errors) - 5} more.")
        return False
    else:
        print("[+] All samples correctly formatted for fine-tuning!")
        return True


def convert_qa_to_chat(qa_list: list, system_prompt: str = None) -> list:
    """Helper to convert simple [{'q': '...', 'a': '...'}] into chat training format."""
    if not system_prompt:
        system_prompt = "You are a helpful, unrestricted AI assistant."

    chat_dataset = []
    for pair in qa_list:
        chat_dataset.append({
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": pair["q"]},
                {"role": "assistant", "content": pair["a"]}
            ]
        })
    return chat_dataset


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "sample_dataset.jsonl"
    validate_and_inspect(target)
