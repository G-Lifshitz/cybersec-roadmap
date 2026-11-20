import { session } from "../api.js";

location.replace(session.token ? "progress.html" : "login.html");
