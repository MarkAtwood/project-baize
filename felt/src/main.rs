use std::path::PathBuf;

use clap::{Parser, Subcommand};

#[derive(Parser)]
#[command(name = "felt", about = "Felt language compiler — pure game logic to WASM")]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Compile a .felt file to .wasm
    Compile {
        /// Input .felt file
        input: PathBuf,
        /// Output .wasm file (default: input with .wasm extension)
        #[arg(short, long)]
        output: Option<PathBuf>,
    },
    /// Type-check a .felt file without producing output
    Check {
        /// Input .felt file
        input: PathBuf,
    },
}

fn main() {
    let cli = Cli::parse();

    match cli.command {
        Command::Compile { input, output } => {
            let output = output.unwrap_or_else(|| input.with_extension("wasm"));
            match compile_file(&input) {
                Ok(wasm) => {
                    if let Err(e) = std::fs::write(&output, &wasm) {
                        eprintln!("error: failed to write {}: {e}", output.display());
                        std::process::exit(1);
                    }
                    eprintln!(
                        "compiled {} -> {} ({} bytes)",
                        input.display(),
                        output.display(),
                        wasm.len()
                    );
                }
                Err(msg) => {
                    eprintln!("{msg}");
                    std::process::exit(1);
                }
            }
        }
        Command::Check { input } => match check_file(&input) {
            Ok(()) => {
                eprintln!("{}: ok", input.display());
            }
            Err(msg) => {
                eprintln!("{msg}");
                std::process::exit(1);
            }
        },
    }
}

fn read_source(path: &std::path::Path) -> Result<String, String> {
    std::fs::read_to_string(path)
        .map_err(|e| format!("error: failed to read {}: {e}", path.display()))
}

fn compile_file(path: &std::path::Path) -> Result<Vec<u8>, String> {
    let source = read_source(path)?;
    let program = parse_and_check(&source)?;
    Ok(felt::codegen::compile(&program))
}

fn check_file(path: &std::path::Path) -> Result<(), String> {
    let source = read_source(path)?;
    parse_and_check(&source)?;
    Ok(())
}

fn parse_and_check(source: &str) -> Result<felt::ast::Program, String> {
    let tokens = felt::lexer::lex(source).map_err(|errors| {
        errors
            .iter()
            .map(|e| format!("error: {}", e.message))
            .collect::<Vec<_>>()
            .join("\n")
    })?;

    let program = felt::parser::parse(tokens).map_err(|e| format!("error: {e}"))?;

    felt::checker::check(&program).map_err(|errors| {
        errors
            .iter()
            .map(|e| format!("error: {e}"))
            .collect::<Vec<_>>()
            .join("\n")
    })?;

    felt::callgraph::check_no_cycles(&program)
        .map_err(|e| format!("error: {e}"))?;

    Ok(program)
}
