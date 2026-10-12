import {defineConfig} from "vitest/config";

// Unit tests for the pure helpers in src/utils and src/services. Run with `npm test` (here or from the project root).
export default defineConfig({
    test: {
        environment: "node",
        include: ["test/**/*.test.{js,jsx}"],
        setupFiles: ["./test/setup.js"],
    },
});
