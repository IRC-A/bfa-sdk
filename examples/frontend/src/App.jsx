// App.jsx
import { BrowserRouter as Router, Routes, Route } from "react-router-dom";
import { StateProvider } from "./StateContext";
import ChatPage from "./ChatPage";
import StateUtilPage from "./StateUtilPage";
import RegistryPage from "./RegistryPage";
import LogsPage from "./LogsPage";

export default function App() {
    return (
        <StateProvider>
        <Router>
            <Routes>
                <Route path="/" element={<ChatPage/>} />
                <Route path="/state-util" element={<StateUtilPage/>} />
                <Route path="/registry" element={<RegistryPage/>} />
                <Route path="/logs" element={<LogsPage/>} />
            </Routes>
        </Router>
        </StateProvider>
    );
}