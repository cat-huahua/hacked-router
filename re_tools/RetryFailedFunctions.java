// Retry only explicitly failed functions in an existing, matching analysis database.
// Invoke with -process -recursive -noanalysis; never import or execute target code.
// Arguments: <private-modules-root> <new-or-existing-private-retry-root>
// Both trees use SHA-256 directory names. Original exports are never overwritten.
// @category Firmware
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

public class RetryFailedFunctions extends GhidraScript {
    private static final int TIMEOUT_SECONDS = 120;

    private static void rejectGit(Path path) {
        for (Path p = path; p != null; p = p.getParent()) {
            if (Files.exists(p.resolve(".git")))
                throw new IllegalArgumentException("Output and input must remain outside Git");
        }
    }

    // Resolve existing ancestors too, so a symlink cannot hide a Git output path.
    private static Path canonicalDestination(Path path) throws Exception {
        path = path.toAbsolutePath().normalize();
        Path ancestor = path;
        while (!Files.exists(ancestor)) ancestor = ancestor.getParent();
        return ancestor.toRealPath().resolve(ancestor.relativize(path)).normalize();
    }

    private static String hash(Path path) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (var stream = Files.newInputStream(path)) {
            byte[] buffer = new byte[65536];
            int n;
            while ((n = stream.read(buffer)) != -1) digest.update(buffer, 0, n);
        }
        return HexFormat.of().formatHex(digest.digest());
    }

    private static String comment(String value) {
        return String.valueOf(value).replace("*/", "* /");
    }

    private static BufferedWriter privateWriter(Path path) throws Exception {
        Files.createFile(path, PosixFilePermissions.asFileAttribute(
            PosixFilePermissions.fromString("rw-------")));
        return Files.newBufferedWriter(path, StandardCharsets.UTF_8, StandardOpenOption.WRITE);
    }

    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 2)
            throw new IllegalArgumentException("Supply modules root and separate private retry root");
        String digest = currentProgram.getExecutableSHA256();
        if (digest == null || !digest.matches("[a-fA-F0-9]{64}"))
            throw new IllegalStateException("Program has no valid executable SHA-256");
        digest = digest.toLowerCase();
        Path modules = Path.of(args[0]).toRealPath();
        Path retryRoot = canonicalDestination(Path.of(args[1]));
        rejectGit(modules);
        rejectGit(retryRoot);
        if (retryRoot.startsWith(modules))
            throw new IllegalArgumentException("Retry root must be separate from original modules tree");
        Path source = modules.resolve(digest);
        Path summaryPath = source.resolve("summary.json");
        if (!Files.isRegularFile(summaryPath)) {
            println("RETRY_SKIP sha256=" + digest + " reason=no_original_summary");
            return;
        }
        source = source.toRealPath();
        if (!source.startsWith(modules)) throw new IllegalArgumentException("Source escapes modules tree");
        summaryPath = source.resolve("summary.json");
        if (!summaryPath.toRealPath().startsWith(modules))
            throw new IllegalArgumentException("Summary escapes modules tree");
        JsonObject original = JsonParser.parseString(Files.readString(summaryPath)).getAsJsonObject();
        if (!digest.equalsIgnoreCase(original.get("input_sha256").getAsString()))
            throw new IllegalStateException("Original summary SHA-256 differs from current program");
        int originalFailed = original.get("failed_functions").getAsInt();
        int originalRecognized = original.get("recognized_functions").getAsInt();
        int originalCompleted = original.get("decompiled_functions").getAsInt();
        if (originalFailed < 0 || originalCompleted < 0 || originalRecognized < 0 ||
                originalFailed + originalCompleted != originalRecognized)
            throw new IllegalStateException("Original summary counts are inconsistent");
        if (originalFailed == 0) {
            println("RETRY_SKIP sha256=" + digest + " reason=no_recorded_failed_functions" +
                    " all_machine_code_proven_covered=false");
            return;
        }
        Path indexPath = source.resolve("functions.jsonl");
        if (!indexPath.toRealPath().startsWith(modules))
            throw new IllegalArgumentException("Function index escapes modules tree");
        String sourceSummaryHash = hash(summaryPath);
        String sourceIndexHash = hash(indexPath);
        List<JsonObject> candidates = new ArrayList<>();
        Set<String> addresses = new HashSet<>();
        int indexed = 0, indexedCompleted = 0;
        try (BufferedReader reader = Files.newBufferedReader(indexPath, StandardCharsets.UTF_8)) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.isBlank()) continue;
                JsonObject row = JsonParser.parseString(line).getAsJsonObject();
                String address = row.get("address").getAsString();
                if (!addresses.add(address)) throw new IllegalStateException("Duplicate original function address");
                if (!row.has("decompiled") || !row.get("decompiled").isJsonPrimitive() ||
                        !row.get("decompiled").getAsJsonPrimitive().isBoolean())
                    throw new IllegalStateException("Missing boolean decompiled field");
                indexed++;
                if (row.get("decompiled").getAsBoolean()) indexedCompleted++;
                else candidates.add(row);
            }
        }
        if (indexed != originalRecognized || indexedCompleted != originalCompleted ||
                candidates.size() != originalFailed)
            throw new IllegalStateException("Original index does not agree with original summary");

        Files.createDirectories(retryRoot, PosixFilePermissions.asFileAttribute(
            PosixFilePermissions.fromString("rwx------")));
        Path out = retryRoot.resolve(digest);
        Files.createDirectory(out, PosixFilePermissions.asFileAttribute(
            PosixFilePermissions.fromString("rwx------")));
        Gson gson = new Gson();
        int completed = 0, failed = 0;
        DecompInterface decompiler = new DecompInterface();
        try {
            if (!decompiler.openProgram(currentProgram)) throw new IllegalStateException(decompiler.getLastMessage());
            try (BufferedWriter code = privateWriter(out.resolve("retry-pseudocode.c"));
                 BufferedWriter index = privateWriter(out.resolve("retry-functions.jsonl"))) {
                code.write("/* Retry pseudocode, not original source. Contains private firmware data.\n" +
                           " * Only originally failed functions are attempted; coverage remains incomplete. */\n");
                for (JsonObject old : candidates) {
                    monitor.checkCancelled();
                    String entry = old.get("address").getAsString();
                    Address address = currentProgram.getAddressFactory().getAddress(entry);
                    Function function = address == null ? null :
                        currentProgram.getFunctionManager().getFunctionAt(address);
                    String error = null;
                    boolean ok = false;
                    code.write("\n/* " + comment(entry) + " " + comment(old.get("name").getAsString()) + " */\n");
                    if (function == null || function.isExternal()) {
                        error = "Original function entry not present as an internal function in this database";
                    } else {
                        DecompileResults result = decompiler.decompileFunction(function, TIMEOUT_SECONDS, monitor);
                        ok = result.decompileCompleted() && result.getDecompiledFunction() != null;
                        if (ok) {
                            code.write(result.getDecompiledFunction().getC());
                            code.newLine();
                        } else error = result.getErrorMessage();
                    }
                    if (ok) completed++;
                    else {
                        failed++;
                        code.write("/* RETRY FAILED: " + comment(error) + " */\n");
                    }
                    Map<String,Object> row = new LinkedHashMap<>();
                    row.put("address", entry);
                    row.put("name", function == null ? old.get("name").getAsString() : function.getName());
                    row.put("decompiled", ok);
                    row.put("error", error);
                    row.put("original_error", old.has("error") ? old.get("error") : null);
                    row.put("timeout_seconds", TIMEOUT_SECONDS);
                    index.write(gson.toJson(row));
                    index.newLine();
                }
            }
        } finally {
            decompiler.dispose();
        }
        if (!sourceSummaryHash.equals(hash(summaryPath)) || !sourceIndexHash.equals(hash(indexPath)))
            throw new IllegalStateException("Original exports changed during retry; no completed summary written");
        Map<String,Object> summary = new LinkedHashMap<>();
        summary.put("program", currentProgram.getName());
        summary.put("input_sha256", digest);
        summary.put("language", currentProgram.getLanguageID().toString());
        summary.put("source_summary_sha256", sourceSummaryHash);
        summary.put("source_index_sha256", sourceIndexHash);
        summary.put("original_recognized_functions", originalRecognized);
        summary.put("original_decompiled_functions", originalCompleted);
        summary.put("original_failed_functions", originalFailed);
        summary.put("attempted_functions", candidates.size());
        summary.put("decompiled_functions", completed);
        summary.put("failed_functions", failed);
        summary.put("timeout_seconds", TIMEOUT_SECONDS);
        summary.put("scope", "Only original functions.jsonl entries with decompiled=false");
        summary.put("all_machine_code_proven_covered", false);
        summary.put("target_code_executed", false);
        try (BufferedWriter writer = privateWriter(out.resolve("retry-summary.json"))) {
            writer.write(gson.toJson(summary));
        }
        println("RETRY_DONE sha256=" + digest + " attempted=" + candidates.size() +
                " decompiled=" + completed + " failed=" + failed);
    }
}
