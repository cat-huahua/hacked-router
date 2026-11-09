// Seed static Ghidra analysis from the verified WE410443-ST kernel symbol export.
// @category Firmware
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.SourceType;
import com.google.gson.Gson;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

public class ImportKernelKallsyms extends GhidraScript {
    private static final String SHA256 = "9ccc2e7356de88658bbd1c905035695fc032f4784e697ec28cc3cc5c2cd4fb7a";
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 2) throw new IllegalArgumentException("Supply symbols.tsv and private import-summary.json");
        if (!SHA256.equalsIgnoreCase(currentProgram.getExecutableSHA256()) ||
            !"MIPS:LE:32:default".equals(currentProgram.getLanguageID().toString()) ||
            currentProgram.getMinAddress().getOffset() != 0x81001000L)
            throw new IllegalArgumentException("Kernel identity, language or base mismatch");
        Path output = Path.of(args[1]).toAbsolutePath().normalize();
        Path parent = output.getParent().toRealPath();
        for (Path p = parent; p != null; p = p.getParent())
            if (Files.exists(p.resolve(".git"))) throw new IllegalArgumentException("Output must be outside Git");
        List<String[]> records = new ArrayList<>();
        for (String line : Files.readAllLines(Path.of(args[0]))) {
            String[] fields = line.split("\t", 3);
            if (fields.length != 3 || fields[1].length() != 1)
                throw new IllegalArgumentException("Malformed symbol row");
            records.add(fields);
        }
        if (records.size() != 32911) throw new IllegalArgumentException("Unexpected symbol count");
        AddressSet text = new AddressSet();
        text.addRange(toAddr(0x81001400L), toAddr(0x8152cf9fL));
        text.addRange(toAddr(0x81734000L), toAddr(0x81758ca3L));
        // Inferred exit-text region: follows __con_initcall_end and precedes
        // __per_cpu_load. Do not decode intervening init data merely because
        // kallsyms labels those records T/t in this vendor kernel.
        text.addRange(toAddr(0x81760c80L), toAddr(0x81761fffL));
        Set<String> boundaries = Set.of("_stext", "_sinittext", "_einittext", "_text", "_etext");
        Map<Address,String> functions = new LinkedHashMap<>();
        int labels = 0, outside = 0, labelErrors = 0, codeOutside = 0;
        for (String[] row : records) {
            monitor.checkCancelled();
            Address address = toAddr(Long.parseUnsignedLong(row[0], 16));
            if (!currentProgram.getMemory().contains(address)) { outside++; continue; }
            try { createLabel(address, row[2], false, SourceType.IMPORTED); labels++; }
            catch (Exception error) { labelErrors++; }
            boolean code = row[1].equals("T") || row[1].equals("t") || row[1].equals("W");
            if (code && !boundaries.contains(row[2])) {
                if (!text.contains(address) || (address.getOffset() & 3) != 0) { codeOutside++; continue; }
                functions.putIfAbsent(address, row[2]);
            }
        }
        AddressSet starts = new AddressSet();
        for (Address address : functions.keySet()) starts.add(address);
        DisassembleCommand command = new DisassembleCommand(starts, text, true);
        command.enableCodeAnalysis(false);
        boolean disassembled = command.applyTo(currentProgram, monitor);
        int created = 0, failed = 0;
        for (Map.Entry<Address,String> entry : functions.entrySet()) {
            monitor.checkCancelled();
            Function function = getFunctionAt(entry.getKey());
            if (function == null) function = createFunction(entry.getKey(), entry.getValue());
            if (function != null) created++; else failed++;
        }
        Map<String,Object> summary = new LinkedHashMap<>();
        summary.put("input_sha256", SHA256);
        summary.put("symbol_records", records.size());
        summary.put("labels_imported", labels);
        summary.put("labels_outside_file_memory", outside);
        summary.put("label_errors", labelErrors);
        summary.put("text_candidates_outside_ranges_or_unaligned", codeOutside);
        summary.put("function_seed_addresses", functions.size());
        summary.put("functions_created_or_present", created);
        summary.put("function_creation_failed", failed);
        summary.put("disassembly_command_result", disassembled);
        summary.put("disassembly_status", command.getStatusMsg());
        summary.put("weak_symbols_in_text_treated_as_function_candidates", true);
        summary.put("exit_text_range_inferred", "81760c80-81761fff");
        summary.put("all_machine_code_proven_covered", false);
        Files.writeString(output, new Gson().toJson(summary));
        println("Kernel symbols=" + records.size() + " function seeds=" + functions.size() +
                " created/present=" + created + " failed=" + failed);
    }
}
