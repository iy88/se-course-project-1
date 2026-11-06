//! Optional local process observations. ps CPU is OS-reported, not a proof of
//! backend saturation. No command lines or inherited secrets are inspected.
use serde_json::{Value, json};
use tokio::sync::watch;

pub(crate) fn start(
    mut pids: Vec<u32>,
) -> (watch::Sender<bool>, tokio::task::JoinHandle<Vec<Value>>) {
    pids.push(std::process::id());
    pids.sort();
    pids.dedup();
    let (tx, mut rx) = watch::channel(false);
    let task = tokio::spawn(async move {
        let start = std::time::Instant::now();
        let mut values = vec![];
        loop {
            let ids = pids
                .iter()
                .map(u32::to_string)
                .collect::<Vec<_>>()
                .join(",");
            let processes=tokio::task::spawn_blocking(move || {
                let Ok(output)=std::process::Command::new("ps").args(["-p",&ids,"-o","pid=,pcpu=,rss="]).output() else {return vec![];};
                String::from_utf8_lossy(&output.stdout).lines().filter_map(|line| {
                    let parts=line.split_whitespace().collect::<Vec<_>>();
                    if parts.len()!=3 {return None;}
                    Some(json!({"pid":parts[0].parse::<u32>().ok()?,"cpu_reported_pct":parts[1].parse::<f64>().ok()?,"rss_kib":parts[2].parse::<u64>().ok()?}))
                }).collect::<Vec<Value>>()
            }).await.unwrap_or_default();
            values.push(
                json!({"elapsed_seconds":start.elapsed().as_secs_f64(),"processes":processes}),
            );
            tokio::select! {
                _=tokio::time::sleep(std::time::Duration::from_secs(1))=>{},
                _=rx.changed()=>break,
            }
        }
        values
    });
    (tx, task)
}
