// Centralized configuration for BFA Gateway connection
export const GATEWAY_URL = (
    process.env.REACT_APP_GATEWAY_URL || 
    window.REACT_APP_GATEWAY_URL || 
    "http://localhost:8000"
).replace(/\/$/, "");
