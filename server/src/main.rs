mod config;
mod connection;
mod protocol;
mod room;
mod vault;
#[cfg(feature = "wasm-host")]
mod wasm_host;

use std::net::SocketAddr;
use std::sync::Arc;

use axum::Router;
use axum::routing::get;
use room::RoomRegistry;

#[tokio::main]
async fn main() {
    let registry = Arc::new(RoomRegistry::new());

    let app = Router::new()
        .route("/ws/{room_id}", get(connection::ws_handler))
        .route("/health", get(health))
        .with_state(registry);

    let listener = tokio::net::TcpListener::bind("0.0.0.0:8080")
        .await
        .expect("failed to bind port 8080");

    eprintln!("baize-server listening on 0.0.0.0:8080");
    axum::serve(
        listener,
        app.into_make_service_with_connect_info::<SocketAddr>(),
    )
    .await
    .expect("server error");
}

async fn health() -> &'static str {
    "ok"
}
