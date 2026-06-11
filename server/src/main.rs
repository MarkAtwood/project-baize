mod config;
mod connection;
mod protocol;
mod room;
mod store;
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
    let data_dir = std::env::var("BAIZE_DATA_DIR").unwrap_or_else(|_| "data".to_string());
    let store = match store::FileStore::new(&data_dir) {
        Ok(s) => {
            eprintln!("persistence enabled: {data_dir}/");
            Arc::new(s) as Arc<dyn store::Store>
        }
        Err(e) => {
            eprintln!("warning: persistence disabled ({e}), running in-memory only");
            Arc::new(store::MemoryStore::new()) as Arc<dyn store::Store>
        }
    };
    let registry = Arc::new(RoomRegistry::with_store(store));

    match registry.restore_from_store().await {
        Ok(0) => {}
        Ok(n) => eprintln!("restored {n} room(s) from store"),
        Err(e) => eprintln!("warning: failed to restore rooms: {e}"),
    }

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
