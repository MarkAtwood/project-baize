mod config;
mod connection;
mod protocol;
mod room;
#[allow(dead_code)]
mod vault;
#[cfg(feature = "wasm-host")]
mod wasm_host;

use std::net::SocketAddr;
use std::sync::Arc;

use axum::Router;
use axum::routing::{get, post};
use room::RoomRegistry;
use tower_http::cors::{Any, CorsLayer};

#[tokio::main]
async fn main() {
    let registry = Arc::new(RoomRegistry::new());

    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods(Any)
        .allow_headers(Any);

    let app = Router::new()
        .route("/rooms", post(connection::create_room_handler))
        .route("/rooms", get(connection::list_rooms_handler))
        .route("/ws/{room_id}", get(connection::ws_handler))
        .route("/health", get(health))
        .layer(cors)
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
