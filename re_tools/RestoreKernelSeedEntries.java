// Restore validated symbol entry candidates in a private refined analysis copy.
// Does not clear existing code/data, force body bounds, execute or patch firmware.
// @category Firmware
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Program;
import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.google.gson.JsonElement;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

public class RestoreKernelSeedEntries extends GhidraScript {
    private String hash(Path path) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(path)));
    }
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 3) throw new IllegalArgumentException("Supply private gap audit, symbols.tsv, and new output JSON");
        String expected = "9ccc2e7356de88658bbd1c905035695fc032f4784e697ec28cc3cc5c2cd4fb7a";
        if (!expected.equalsIgnoreCase(currentProgram.getExecutableSHA256()) ||
            !"MIPS:LE:32:default".equals(currentProgram.getLanguageID().toString()))
            throw new IllegalStateException("Verified kernel identity/language required");
        Path auditPath = Path.of(args[0]).toRealPath();
        Path symbolsPath = Path.of(args[1]).toRealPath();
        Path output = Path.of(args[2]).toAbsolutePath().normalize();
        if (Files.exists(output)) throw new IllegalArgumentException("Output already exists");
        for (Path p = output.getParent().toRealPath(); p != null; p = p.getParent())
            if (Files.exists(p.resolve(".git"))) throw new IllegalArgumentException("Use private output outside Git");
        if (currentProgram.getOptions(Program.ANALYSIS_PROPERTIES).getBoolean("Non-Returning Functions - Discovered", true))
            throw new IllegalStateException("Apply the verified printk flow repair profile first");
        Set<String> validated = new HashSet<>();
        for (String line : Files.readAllLines(symbolsPath)) {
            String[] fields = line.split("\t", 3);
            if (fields.length == 3 && Set.of("T", "t", "W").contains(fields[1]))
                validated.add(fields[0].toLowerCase() + "\t" + fields[2]);
        }
        JsonObject audit = JsonParser.parseString(Files.readString(auditPath)).getAsJsonObject();
        if (audit.getAsJsonArray("missing_seed_records").size() != audit.get("seed_not_exported_as_entry").getAsInt())
            throw new IllegalStateException("Gap audit counts differ");
        AddressSet allowed = new AddressSet();
        allowed.addRange(toAddr(0x81001400L), toAddr(0x8152cf9fL));
        allowed.addRange(toAddr(0x81734000L), toAddr(0x81758ca3L));
        allowed.addRange(toAddr(0x81760c80L), toAddr(0x81761fffL));
        List<Map<String,Object>> rows = new ArrayList<>();
        Map<String,Integer> counts = new LinkedHashMap<>();
        Set<String> visited = new HashSet<>();
        int before = currentProgram.getFunctionManager().getFunctionCount();
        for (JsonElement element : audit.getAsJsonArray("missing_seed_records")) {
            monitor.checkCancelled();
            JsonObject seed = element.getAsJsonObject();
            String entry = seed.get("address").getAsString().toLowerCase();
            String name = seed.get("name").getAsString();
            if (!validated.contains(entry + "\t" + name) || !visited.add(entry))
                throw new IllegalStateException("Seed is absent from verified symbols or duplicated");
            Address address = toAddr(Long.parseUnsignedLong(entry, 16));
            Map<String,Object> row = new LinkedHashMap<>();
            row.put("address", entry); row.put("name", name);
            String outcome;
            Function function = getFunctionAt(address);
            if (!allowed.contains(address) || (address.getOffset() & 3) != 0)
                outcome = "outside_text_or_unaligned";
            else if (function != null) outcome = "already_present";
            else if (getFunctionContaining(address) != null) {
                outcome = "inside_existing_function_not_redefined";
                row.put("containing_function", getFunctionContaining(address).getEntryPoint().toString());
            } else if (currentProgram.getListing().getDefinedDataContaining(address) != null)
                outcome = "defined_data_not_cleared";
            else {
                if (getInstructionAt(address) == null) {
                    DisassembleCommand command = new DisassembleCommand(new AddressSet(address), allowed, true);
                    command.enableCodeAnalysis(false);
                    row.put("disassembly_result", command.applyTo(currentProgram, monitor));
                }
                if (getInstructionAt(address) == null) outcome = "no_exact_entry_instruction";
                else {
                    function = createFunction(address, name);
                    outcome = function == null ? "automatic_creation_failed" : "created_by_flow";
                }
            }
            if (function != null) {
                row.put("body", function.getBody().toString());
                row.put("no_return", function.hasNoReturn());
            }
            row.put("outcome", outcome); rows.add(row);
            counts.put(outcome, counts.getOrDefault(outcome, 0) + 1);
        }
        Map<String,Object> result = new LinkedHashMap<>();
        result.put("input_sha256", expected);
        result.put("gap_audit_sha256", hash(auditPath));
        result.put("symbols_tsv_sha256", hash(symbolsPath));
        result.put("candidate_count", rows.size());
        result.put("function_count_before", before);
        result.put("function_count_after", currentProgram.getFunctionManager().getFunctionCount());
        result.put("outcome_counts", counts); result.put("candidates", rows);
        result.put("manual_function_body_bounds", false);
        result.put("existing_code_or_data_cleared", false);
        result.put("firmware_bytes_modified", false);
        result.put("decompilation_attempted", false);
        result.put("all_machine_code_proven_covered", false);
        Files.writeString(output, new Gson().toJson(result));
        println("Kernel seed restoration " + counts);
    }
}
