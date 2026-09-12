"""
Fine-tuning script with LoRA / PEFT.
Supports Apple Silicon (MPS), NVIDIA CUDA, and CPU.
On M4 Pro (37GB unified): can fine-tune 7B-13B models comfortably.
"""

import os
import sys
import torch
from datasets import load_dataset


def detect_device():
    if torch.cuda.is_available():
        name = torch.cuda.get_device_name(0)
        vram = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        print(f"[+] CUDA GPU: {name} ({vram:.1f} GB VRAM)")
        return "cuda"

    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        # Apple Silicon — unified memory, treat like a large GPU
        import subprocess
        try:
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True
            )
            total_ram_gb = int(result.stdout.strip()) / (1024 ** 3)
        except Exception:
            total_ram_gb = 0
        print(f"[+] Apple Silicon MPS ({total_ram_gb:.0f} GB unified memory)")
        print("[+] M4 Pro recommendation: train 7B-13B models in bf16, or 30B+ with LoRA r=4")
        return "mps"

    print("[-] No GPU found — training on CPU (very slow)")
    return "cpu"


def main():
    print("=" * 60)
    print("  Local LLM LoRA Fine-Tuner — Apple M4 Pro / CUDA / CPU  ")
    print("=" * 60)

    device = detect_device()

    dataset_path = "sample_dataset.jsonl"
    if not os.path.exists(dataset_path):
        print(f"[-] Dataset {dataset_path} not found.")
        sys.exit(1)

    print(f"[*] Loading training dataset: {dataset_path}")
    dataset = load_dataset("json", data_files=dataset_path, split="train")
    print(f"[+] Loaded {len(dataset)} training samples.")

    try:
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            TrainingArguments,
            BitsAndBytesConfig,
        )
        from peft import LoraConfig, get_peft_model, TaskType
        from trl import SFTTrainer
    except ImportError as e:
        print(f"[-] Missing required library: {e}")
        print("    Install: pip install transformers peft trl datasets accelerate bitsandbytes")
        sys.exit(1)

    # On M4 Pro (37GB): can comfortably run Qwen2.5-7B, Llama-3.1-8B, or Mistral-7B
    # For 13B: use LoRA with r=8, batch_size=1, gradient_accum=8
    # For 30B+: use LoRA with r=4, batch_size=1, gradient_accum=16
    model_id = os.environ.get(
        "BASE_MODEL",
        "Qwen/Qwen2.5-7B-Instruct"  # Good default for M4 Pro — runs in ~14GB
    )
    output_dir = "./custom_lora_output"

    # Apple Silicon uses bf16 natively (no fp16 support)
    use_bf16 = device in ("mps", "cpu")
    use_fp16 = device == "cuda"

    print(f"[*] Loading tokenizer for {model_id}...")
    tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    print(f"[*] Loading model {model_id}...")
    load_kwargs = {
        "trust_remote_code": True,
    }

    if device == "cuda":
        load_kwargs["torch_dtype"] = torch.float16
        load_kwargs["device_map"] = "auto"
    elif device == "mps":
        # MPS: load in bf16 on CPU first, then move to MPS
        load_kwargs["torch_dtype"] = torch.bfloat16
        load_kwargs["device_map"] = {"": "mps"}
    else:
        load_kwargs["torch_dtype"] = torch.float32

    model = AutoModelForCausalLM.from_pretrained(model_id, **load_kwargs)

    if hasattr(model, "gradient_checkpointing_enable"):
        model.gradient_checkpointing_enable()

    # LoRA config — r=16 on M4 Pro is fine for 7B models
    lora_r = int(os.environ.get("LORA_RANK", "16" if device == "mps" else "8"))
    lora_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=lora_r,
        lora_alpha=lora_r * 2,
        lora_dropout=0.05,
        target_modules=["q_proj", "v_proj", "k_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        bias="none",
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # Training arguments
    # M4 Pro: batch_size=2 for 7B, batch_size=1 for 13B+
    batch_size = int(os.environ.get("BATCH_SIZE", "2" if device == "mps" else "1"))
    training_args = TrainingArguments(
        output_dir=output_dir,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=4,
        learning_rate=2e-4,
        num_train_epochs=3,
        logging_steps=1,
        bf16=use_bf16,
        fp16=use_fp16,
        optim="adamw_torch",
        save_strategy="epoch",
        save_total_limit=2,
        report_to="none",
        # MPS workaround: disable dataloader multiprocessing
        dataloader_num_workers=0 if device == "mps" else 4,
    )

    trainer = SFTTrainer(
        model=model,
        train_dataset=dataset,
        args=training_args,
    )

    print(f"\n[+] Starting fine-tuning on {device.upper()}...")
    trainer.train()

    print(f"\n[+] Fine-tuning complete! Saving adapter to {output_dir}...")
    trainer.model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)
    print(f"[+] Done. Load with: AutoModelForCausalLM + PeftModel.from_pretrained('{output_dir}')")
    print(f"    Or merge and push to Ollama using: ollama create my-model -f ./Modelfile.custom")


if __name__ == "__main__":
    main()
