// Read-only inspection of function return metadata, instructions and call sites.
// @category Firmware
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.listing.Program;
import ghidra.program.model.listing.Bookmark;
import ghidra.program.model.listing.CodeUnit;
import ghidra.program.model.listing.Data;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import ghidra.framework.options.Options;
import com.google.gson.Gson;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class InspectFunctionReturns extends GhidraScript {
    private Map<String,Object> instruction(Instruction instruction) {
        Map<String,Object> row = new LinkedHashMap<>();
        row.put("address", instruction.getAddress().toString());
        row.put("text", instruction.toString());
        row.put("flow_type", instruction.getFlowType().toString());
        row.put("flow_override", instruction.getFlowOverride().toString());
        row.put("fallthrough", instruction.getFallThrough() == null ? null : instruction.getFallThrough().toString());
        row.put("default_fallthrough", instruction.getDefaultFallThrough() == null ? null : instruction.getDefaultFallThrough().toString());
        List<Map<String,Object>> targets = new ArrayList<>();
        for (Address target : instruction.getFlows()) {
            Function callee = getFunctionAt(target);
            Map<String,Object> item = new LinkedHashMap<>();
            item.put("address", target.toString());
            if (callee != null) { item.put("name", callee.getName()); item.put("no_return", callee.hasNoReturn()); }
            targets.add(item);
        }
        row.put("targets", targets);
        return row;
    }

    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) throw new IllegalArgumentException("Supply private JSON path and function addresses");
        Path output = Path.of(args[0]).toAbsolutePath().normalize();
        Path parent = output.getParent().toRealPath();
        for (Path p = parent; p != null; p = p.getParent())
            if (Files.exists(p.resolve(".git"))) throw new IllegalArgumentException("Output must be outside Git");
        List<Map<String,Object>> rows = new ArrayList<>();
        for (int i = 1; i < args.length; i++) {
            monitor.checkCancelled();
            Address address = toAddr(Long.parseUnsignedLong(args[i].replaceFirst("^0x", ""), 16));
            Map<String,Object> row = new LinkedHashMap<>();
            row.put("address", address.toString());
            Function function = getFunctionAt(address);
            row.put("function_exists", function != null);
            Function containing = getFunctionContaining(address);
            row.put("containing_function", containing == null ? null : containing.getName());
            CodeUnit unit = currentProgram.getListing().getCodeUnitContaining(address);
            if (unit != null) {
                row.put("entry_code_unit_kind", unit.getClass().getSimpleName());
                row.put("entry_code_unit_address", unit.getAddress().toString());
                row.put("entry_code_unit_length", unit.getLength());
                if (unit instanceof Data) row.put("entry_data_type", ((Data)unit).getDataType().getName());
            }
            List<Map<String,String>> bookmarks = new ArrayList<>();
            for (Bookmark bookmark : currentProgram.getBookmarkManager().getBookmarks(address)) {
                bookmarks.add(Map.of("type", bookmark.getTypeString(), "category", bookmark.getCategory(),
                                     "comment", bookmark.getComment()));
            }
            row.put("entry_bookmarks", bookmarks);
            List<Map<String,Object>> prefix = new ArrayList<>();
            for (int offset = 0; offset < 80; offset += 4) {
                Instruction ins = getInstructionAt(address.add(offset));
                if (ins != null) prefix.add(instruction(ins));
            }
            row.put("entry_instructions", prefix);
            if (function != null) {
                row.put("name", function.getName());
                row.put("no_return", function.hasNoReturn());
                row.put("signature_source", function.getSignatureSource().toString());
                row.put("signature", function.getSignature().toString());
                row.put("body", function.getBody().toString());
                row.put("body_address_count", function.getBody().getNumAddresses());
                List<Map<String,Object>> flow = new ArrayList<>();
                InstructionIterator iterator = currentProgram.getListing().getInstructions(function.getBody(), true);
                while (iterator.hasNext()) {
                    Instruction ins = iterator.next();
                    if (ins.getFlowType().isCall() || ins.getFlowType().isTerminal() ||
                        !ins.getFlowOverride().toString().equals("NONE")) flow.add(instruction(ins));
                }
                row.put("call_terminal_override_instructions", flow);
            }
            List<Map<String,Object>> sites = new ArrayList<>();
            Map<String,Integer> overrides = new LinkedHashMap<>();
            ReferenceIterator references = currentProgram.getReferenceManager().getReferencesTo(address);
            int count = 0;
            while (references.hasNext()) {
                Reference reference = references.next();
                Instruction ins = getInstructionAt(reference.getFromAddress());
                if (ins == null || !reference.getReferenceType().isCall()) continue;
                count++;
                String override = ins.getFlowOverride().toString();
                overrides.put(override, overrides.getOrDefault(override, 0) + 1);
                if (sites.size() < 12 || ins.getAddress().equals(toAddr(0x813f4c30L))) sites.add(instruction(ins));
            }
            row.put("callsite_count", count);
            row.put("callsite_override_counts", overrides);
            row.put("callsite_samples", sites);
            rows.add(row);
        }
        Map<String,Object> result = new LinkedHashMap<>();
        result.put("input_sha256", currentProgram.getExecutableSHA256());
        result.put("functions", rows);
        Options options = currentProgram.getOptions(Program.ANALYSIS_PROPERTIES);
        Map<String,String> settings = new LinkedHashMap<>();
        for (String name : options.getOptionNames()) {
            if (name.toLowerCase().contains("return")) settings.put(name, String.valueOf(options.getObject(name, null)));
        }
        result.put("return_analysis_options", settings);
        result.put("program_modified_by_script", false);
        Files.writeString(output, new Gson().toJson(result));
        println("Inspected " + rows.size() + " addresses without program mutation");
    }
}
