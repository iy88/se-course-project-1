mod capacity;
mod config;
mod diagnostics;
#[cfg(test)]
mod diagnostics_tests;
mod http;
mod model;
mod races;
mod report;
mod resources;
mod runner;
mod scenarios;
mod ws;

use clap::Parser;

#[tokio::main]
async fn main() {
    let args = config::Args::parse();
    match runner::run(&args).await {
        Ok(true) => {}
        Ok(false) => std::process::exit(1),
        Err(error) => {
            eprintln!("Load setup/run failed: {error}");
            std::process::exit(2);
        }
    }
}
