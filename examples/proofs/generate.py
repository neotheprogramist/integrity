import os
import subprocess
import tempfile
import logging
import json
from math import ceil, log

# Setup logging configuration
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# List of layouts to process
LAYOUTS = [
    "dex",
    "recursive",
    "recursive_with_poseidon",
    "small",
    "starknet",
    "starknet_with_keccak",
]
# LAYOUTS = ['dynamic']

# Paths for required files
PARAMETER_FILE = "cpu_air_params.json"
PROVER_CONFIG_FILE = "cpu_air_prover_config.json"
PROGRAM_INPUT_FILE = "fibonacci_input.json"


def run_command(command: list):
    """Run a shell command and log the output or errors."""
    try:
        logging.info(f'Running command: {" ".join(command)}')
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"Command failed: {e}")
        raise


def extract_steps(public_input_file: str) -> int:
    """Extract 'n_steps' from the public input JSON file."""
    with open(public_input_file, "r") as f:
        public_input = json.load(f)
    return public_input.get("n_steps", 0)


def compute_fri_step_list(n_steps: int, config: dict) -> list:
    """Compute a new 'fri_step_list' based on the provided n_steps and config template."""
    n_steps_log = ceil(log(n_steps, 2))
    last_layer_degree_bound_log = ceil(
        log(config["stark"]["fri"]["last_layer_degree_bound"], 2)
    )
    sigma_fri_step_list = n_steps_log + 4 - last_layer_degree_bound_log

    q, r = divmod(sigma_fri_step_list, 4)
    return [0] + [4] * q + ([r] if r > 0 else [])


def update_parameter_file(parameter_file_path: str, tmpdir: str, n_steps: int) -> str:
    """Update the parameter file with a new 'fri_step_list' and save to a temporary file."""
    with open(parameter_file_path, "r") as f:
        config = json.load(f)

    # Update fri_step_list
    config["stark"]["fri"]["fri_step_list"] = compute_fri_step_list(n_steps, config)

    # Save updated config to a temporary file
    updated_file = os.path.join(tmpdir, "updated_cpu_air_params.json")
    with open(updated_file, "w") as f:
        json.dump(config, f, indent=4)

    logging.info(f"Updated parameter file saved: {updated_file}")
    return updated_file


def build_cairo_run_command(
    layout: str,
    compiled_output: str,
    trace_file: str,
    memory_file: str,
    public_input_file: str,
    private_input_file: str,
) -> list:
    """Build the cairo-run command with optional parameters based on the layout."""
    base_command = [
        "cairo-run",
        "--program",
        compiled_output,
        "--layout",
        layout,
        "--proof_mode",
        "--program_input",
        PROGRAM_INPUT_FILE,
        "--trace_file",
        trace_file,
        "--memory_file",
        memory_file,
        "--air_private_input",
        private_input_file,
        "--air_public_input",
        public_input_file,
        "--print_info",
        "--print_output",
    ]

    # Add dynamic layout-specific parameter
    if layout == "dynamic":
        cairo_layout_params_file = os.path.join(layout, "cairo_layout_params.json")
        base_command.extend(["--cairo_layout_params_file", cairo_layout_params_file])

    return base_command


def process_layout(layout: str):
    """Main process for compiling, running, and proving for a given layout."""
    logging.info(f"Processing layout: {layout}")

    with tempfile.TemporaryDirectory() as tmpdir:
        # Compile the Cairo program
        compiled_output = os.path.join(tmpdir, "fibonacci_compiled.json")
        run_command(
            [
                "cairo-compile",
                f"{layout}/cairo0_fibonacci.cairo",
                "--output",
                compiled_output,
                "--no_debug_info",
                "--proof_mode",
            ]
        )

        # Prepare files for the run step
        trace_file = os.path.join(tmpdir, "fibonacci_trace.bin")
        memory_file = os.path.join(tmpdir, "fibonacci_memory.bin")
        public_input_file = os.path.join(tmpdir, "fibonacci_public_input.json")
        private_input_file = os.path.join(tmpdir, "fibonacci_private_input.json")

        # Build and run the Cairo program command
        cairo_run_command = [
            "cairo-run",
            "--program",
            compiled_output,
            "--layout",
            layout,
            "--proof_mode",
            "--program_input",
            PROGRAM_INPUT_FILE,
            "--trace_file",
            trace_file,
            "--memory_file",
            memory_file,
            "--air_private_input",
            private_input_file,
            "--air_public_input",
            public_input_file,
            "--print_info",
            "--print_output",
        ]

        # Add dynamic layout-specific parameter
        if layout == "dynamic":
            cairo_layout_params_file = os.path.join(layout, "cairo_layout_params.json")
            cairo_run_command.extend(
                ["--cairo_layout_params_file", cairo_layout_params_file]
            )

        run_command(cairo_run_command)

        # Update parameter file with new fri_step_list
        n_steps = extract_steps(public_input_file)
        updated_parameter_file = update_parameter_file(PARAMETER_FILE, tmpdir, n_steps)

        # Run the prover
        proof_output = f"{layout}/cairo0_stone6_keccak_160_lsb_example_proof.json"
        run_command(
            [
                "cpu_air_prover",
                "--parameter_file",
                updated_parameter_file,
                "--prover_config_file",
                PROVER_CONFIG_FILE,
                "--public_input_file",
                public_input_file,
                "--private_input_file",
                private_input_file,
                "--out_file",
                proof_output,
                "--generate_annotations",
            ]
        )

        logging.info(f"Proof saved for {layout} in {proof_output}")


# Main execution loop for each layout
for layout in LAYOUTS:
    try:
        process_layout(layout)
    except Exception as e:
        logging.error(f"Error processing layout {layout}: {e}")
        continue

logging.info("Process completed for all layouts.")
