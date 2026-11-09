// Inspect verified kernel symbol candidates missing from the original export.
// Requests rollback of temporary analysis; use -process -noanalysis -readOnly.
// Nested transactions may defer rollback until the outer script transaction ends.
// Independently reopen the database to verify persistence; do not infer it from in-memory counts.
// Never clear existing data/code or impose manual function-body boundaries.
// Arguments: <private-gap-audit.json> <private-original-summary.json> <new-private-output>
// @category Firmware
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import com.google.gson.Gson;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
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
import java.util.HashSet;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;

public class RecoverKernelSeedGaps extends GhidraScript {
    private static final String SHA256 = "9ccc2e7356de88658bbd1c905035695fc032f4784e697ec28cc3cc5c2cd4fb7a";
    private static final int TIMEOUT = 120;

    private static void rejectGit(Path path) {
        for (Path p = path; p != null; p = p.getParent())
            if (Files.exists(p.resolve(".git"))) throw new IllegalArgumentException("Use private paths outside Git");
    }
    private static String hash(Path path) throws Exception {
        MessageDigest d = MessageDigest.getInstance("SHA-256");
        try (var stream = Files.newInputStream(path)) {
            byte[] b = new byte[65536]; int n;
            while ((n = stream.read(b)) != -1) d.update(b, 0, n);
        }
        return HexFormat.of().formatHex(d.digest());
    }
    private static String comment(String text) {
        return String.valueOf(text).replace("*/", "* /");
    }
    private static BufferedWriter privateWriter(Path path) throws Exception {
        Files.createFile(path, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
        return Files.newBufferedWriter(path, StandardCharsets.UTF_8, StandardOpenOption.WRITE);
    }
    private static Path canonicalDestination(Path path) throws Exception {
        path = path.toAbsolutePath().normalize();
        Path ancestor = path;
        while (!Files.exists(ancestor)) ancestor = ancestor.getParent();
        return ancestor.toRealPath().resolve(ancestor.relativize(path)).normalize();
    }

    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 3) throw new IllegalArgumentException("Supply audit, original summary, and new private output");
        if (!SHA256.equalsIgnoreCase(currentProgram.getExecutableSHA256()) ||
                !"MIPS:LE:32:default".equals(currentProgram.getLanguageID().toString()) ||
                currentProgram.getMinAddress().getOffset() != 0x81001000L)
            throw new IllegalStateException("Kernel SHA-256, language or base mismatch");
        Path auditPath = Path.of(args[0]).toRealPath();
        Path originalSummaryPath = Path.of(args[1]).toRealPath();
        Path originalIndexPath = originalSummaryPath.getParent().resolve("functions.jsonl").toRealPath();
        Path out = canonicalDestination(Path.of(args[2]));
        rejectGit(auditPath); rejectGit(originalSummaryPath); rejectGit(originalIndexPath); rejectGit(out);
        if (Files.exists(out)) throw new IllegalArgumentException("Gap output must not already exist");
        JsonObject original = JsonParser.parseString(Files.readString(originalSummaryPath)).getAsJsonObject();
        if (!SHA256.equalsIgnoreCase(original.get("input_sha256").getAsString()))
            throw new IllegalStateException("Original export is not this kernel");
        JsonObject audit = JsonParser.parseString(Files.readString(auditPath)).getAsJsonObject();
        JsonArray records = audit.getAsJsonArray("missing_seed_records");
        if (records == null || records.size() != audit.get("seed_not_exported_as_entry").getAsInt())
            throw new IllegalStateException("Gap audit count mismatch");
        Set<String> originalEntries = new HashSet<>();
        try (BufferedReader reader = Files.newBufferedReader(originalIndexPath, StandardCharsets.UTF_8)) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.isBlank()) continue;
                JsonObject row = JsonParser.parseString(line).getAsJsonObject();
                if (!originalEntries.add(row.get("address").getAsString()))
                    throw new IllegalStateException("Duplicate original function entry");
            }
        }
        if (originalEntries.size() != original.get("recognized_functions").getAsInt() ||
                originalEntries.size() != audit.get("exported_entry_addresses").getAsInt())
            throw new IllegalStateException("Original index/summary/audit counts disagree");
        Set<String> candidates = new HashSet<>();
        for (JsonElement element : records) {
            JsonObject row = element.getAsJsonObject();
            String address = row.get("address").getAsString();
            if (!address.matches("[a-fA-F0-9]{8}") || !candidates.add(address) || originalEntries.contains(address))
                throw new IllegalStateException("Invalid, duplicate, or already exported candidate");
            if (!row.has("name") || !row.has("inside_exported_body"))
                throw new IllegalStateException("Incomplete candidate record");
        }
        String auditHash = hash(auditPath), summaryHash = hash(originalSummaryPath), indexHash = hash(originalIndexPath);
        AddressSet allowed = new AddressSet();
        allowed.addRange(toAddr(0x81001400L), toAddr(0x8152cf9fL));
        allowed.addRange(toAddr(0x81734000L), toAddr(0x81758ca3L));
        allowed.addRange(toAddr(0x81760c80L), toAddr(0x81761fffL));
        Files.createDirectories(out.getParent(), PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        Files.createDirectory(out, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        Gson gson = new Gson();
        int created = 0, existing = 0, completed = 0, failed = 0, notCreated = 0;
        int originalDatabaseFunctions = currentProgram.getFunctionManager().getFunctionCount();
        Map<String,Integer> outcomes = new LinkedHashMap<>();
        int transaction = currentProgram.startTransaction("Temporary static kernel seed gap investigation");
        DecompInterface decompiler = new DecompInterface();
        try {
            if (!decompiler.openProgram(currentProgram)) throw new IllegalStateException(decompiler.getLastMessage());
            try (BufferedWriter code = privateWriter(out.resolve("gap-pseudocode.c"));
                 BufferedWriter asm = privateWriter(out.resolve("gap-assembly.txt"));
                 BufferedWriter index = privateWriter(out.resolve("gap-functions.jsonl"))) {
                code.write("/* Candidate-based static pseudocode, not original or buildable source.\n" +
                           " * Symbol seeds are not proof of true function boundaries.\n" +
                           " * No existing data/code was cleared and no manual body was imposed. */\n");
                asm.write("# Static analysis-memory instructions for recovered candidates; not a runtime trace.\n");
                for (JsonElement element : records) {
                    monitor.checkCancelled();
                    JsonObject seed = element.getAsJsonObject();
                    String entry = seed.get("address").getAsString(), name = seed.get("name").getAsString();
                    Address address = toAddr(Long.parseUnsignedLong(entry, 16));
                    Map<String,Object> row = new LinkedHashMap<>();
                    row.put("address", entry); row.put("seed_name", name);
                    row.put("analysis_candidate_only", true);
                    row.put("originally_inside_exported_body", seed.get("inside_exported_body").getAsBoolean());
                    String outcome = null, error = null;
                    Function function = null;
                    boolean ok = false;
                    try {
                        if (!currentProgram.getMemory().contains(address) || !allowed.contains(address) ||
                                (address.getOffset() & 3) != 0) {
                            outcome = "outside_verified_candidate_ranges_or_unaligned";
                        } else {
                            function = getFunctionAt(address);
                            if (function != null) {
                                existing++;
                                row.put("function_preexisted", true);
                            } else {
                                Function containing = getFunctionContaining(address);
                                if (containing != null) {
                                    outcome = "inside_existing_function_not_redefined";
                                    row.put("containing_function_entry", containing.getEntryPoint().toString());
                                } else if (currentProgram.getListing().getDefinedDataContaining(address) != null) {
                                    outcome = "defined_data_conflict_not_cleared";
                                } else {
                                    if (getInstructionAt(address) == null) {
                                        DisassembleCommand cmd = new DisassembleCommand(new AddressSet(address), allowed, true);
                                        cmd.enableCodeAnalysis(false);
                                        row.put("disassembly_result", cmd.applyTo(currentProgram, monitor));
                                        row.put("disassembly_status", cmd.getStatusMsg());
                                    }
                                    if (getInstructionAt(address) == null) {
                                        outcome = "no_instruction_at_exact_seed_after_disassembly";
                                    } else {
                                        function = createFunction(address, name);
                                        if (function == null) outcome = "automatic_function_creation_failed";
                                        else {
                                            created++;
                                            row.put("function_preexisted", false);
                                        }
                                    }
                                }
                            }
                        }
                        if (function != null) {
                            if (!function.getEntryPoint().equals(address) || function.isExternal())
                                throw new IllegalStateException("Function does not have requested exact internal entry");
                            row.put("function_name", function.getName());
                            row.put("body", function.getBody().toString());
                            code.write("\n/* Candidate " + comment(entry) + " " + comment(name) + " */\n");
                            decompiler.flushCache();
                            DecompileResults result = decompiler.decompileFunction(function, TIMEOUT, monitor);
                            ok = result.decompileCompleted() && result.getDecompiledFunction() != null;
                            if (ok) {
                                code.write(result.getDecompiledFunction().getC()); code.newLine();
                                outcome = "exact_entry_candidate_decompiled";
                            } else {
                                error = result.getErrorMessage(); outcome = "exact_entry_decompilation_failed";
                                code.write("/* DECOMPILATION FAILED: " + comment(error) + " */\n");
                            }
                            asm.write("\n# Candidate " + entry + " " + comment(name) + "\n");
                            InstructionIterator instructions = currentProgram.getListing().getInstructions(function.getBody(), true);
                            while (instructions.hasNext()) {
                                Instruction instruction = instructions.next();
                                asm.write(instruction.getAddress() + "  " + instruction.toString() + "\n");
                            }
                        }
                    } catch (Exception exception) {
                        monitor.checkCancelled();
                        error = exception.getClass().getSimpleName() + ": " + exception.getMessage();
                        outcome = "candidate_analysis_exception";
                    }
                    if (ok) completed++; else failed++;
                    if (function == null) notCreated++;
                    row.put("outcome", outcome); row.put("decompiled", ok); row.put("error", error);
                    row.put("timeout_seconds", TIMEOUT);
                    outcomes.merge(outcome, 1, Integer::sum);
                    index.write(gson.toJson(row)); index.newLine();
                    code.flush(); asm.flush(); index.flush();
                    println("KERNEL_GAP address=" + entry + " outcome=" + outcome);
                }
            }
        } finally {
            decompiler.dispose();
            currentProgram.endTransaction(transaction, false);
        }
        // GhidraScript may own an outer transaction. endTransaction(false) requests
        // rollback, but a nested transaction need not restore the visible count yet.
        // This observation is diagnostic only; persistence requires a fresh reopen.
        int countAfterRollbackRequest = currentProgram.getFunctionManager().getFunctionCount();
        if (!auditHash.equals(hash(auditPath)) || !summaryHash.equals(hash(originalSummaryPath)) ||
                !indexHash.equals(hash(originalIndexPath)))
            throw new IllegalStateException("Input audit or original exports changed during analysis");
        Map<String,Object> summary = new LinkedHashMap<>();
        summary.put("input_sha256", SHA256);
        summary.put("source_audit_sha256", auditHash);
        summary.put("source_summary_sha256", summaryHash);
        summary.put("source_index_sha256", indexHash);
        summary.put("candidate_records", records.size());
        summary.put("functions_created_temporarily", created);
        summary.put("exact_functions_already_in_database", existing);
        summary.put("candidates_without_exact_function", notCreated);
        summary.put("decompiled_functions", completed);
        summary.put("failed_candidates", failed);
        summary.put("outcomes", outcomes);
        summary.put("timeout_seconds", TIMEOUT);
        summary.put("rollback_requested", true);
        summary.put("rollback_completed_in_memory_verified", false);
        summary.put("original_database_function_count", originalDatabaseFunctions);
        summary.put("in_memory_function_count_after_rollback_request", countAfterRollbackRequest);
        summary.put("independent_database_reopen_performed_by_script", false);
        summary.put("persistence_note", "Run this script only in a separate -readOnly headless instance. " +
            "Closing that instance must discard transient changes; independently reopen the database " +
            "and compare entries before claiming the saved database is unchanged. A nested script " +
            "transaction can defer rollback until the outer transaction ends.");
        summary.put("manual_function_boundaries_imposed", false);
        summary.put("existing_data_or_code_cleared", false);
        summary.put("symbol_candidates_proven_function_boundaries", false);
        summary.put("all_machine_code_proven_covered", false);
        summary.put("target_code_executed", false);
        try (BufferedWriter writer = privateWriter(out.resolve("gap-summary.json"))) {
            writer.write(gson.toJson(summary));
        }
        println("KERNEL_GAP_DONE candidates=" + records.size() + " decompiled=" + completed + " failed=" + failed);
    }
}
