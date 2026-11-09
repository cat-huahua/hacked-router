// Read-only candidate audit: a raw JR RA inside a no-return body needs review.
// A return-shaped instruction alone does not prove it is reachable.
// @category Firmware
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.address.Address;
import com.google.gson.Gson;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class AuditKernelNoReturn extends GhidraScript {
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 1) throw new IllegalArgumentException("Supply private output JSON");
        if (!"9ccc2e7356de88658bbd1c905035695fc032f4784e697ec28cc3cc5c2cd4fb7a".equalsIgnoreCase(currentProgram.getExecutableSHA256()))
            throw new IllegalStateException("Verified kernel identity required");
        Path output = Path.of(args[0]).toAbsolutePath().normalize();
        for (Path p = output.getParent().toRealPath(); p != null; p = p.getParent())
            if (Files.exists(p.resolve(".git"))) throw new IllegalArgumentException("Use private output");
        if (Files.exists(output)) throw new IllegalArgumentException("Output already exists");
        List<Map<String,Object>> candidates = new ArrayList<>();
        List<Map<String,Object>> logging = new ArrayList<>();
        int functions = 0, noReturn = 0;
        FunctionIterator iterator = currentProgram.getFunctionManager().getFunctions(true);
        while (iterator.hasNext()) {
            monitor.checkCancelled();
            Function function = iterator.next();
            if (function.isExternal()) continue;
            functions++;
            if (function.getName().toLowerCase().contains("printk")) {
                Map<String,Object> item = new LinkedHashMap<>();
                item.put("entry", function.getEntryPoint().toString());
                item.put("name", function.getName()); item.put("no_return", function.hasNoReturn());
                logging.add(item);
            }
            if (!function.hasNoReturn()) continue;
            noReturn++;
            List<String> returns = new ArrayList<>();
            List<Map<String,Object>> callees = new ArrayList<>();
            InstructionIterator instructions = currentProgram.getListing().getInstructions(function.getBody(), true);
            while (instructions.hasNext()) {
                Instruction instruction = instructions.next();
                int word = currentProgram.getMemory().getInt(instruction.getAddress());
                if ((word & ~0x400) == 0x03e00008) returns.add(instruction.getAddress().toString());
                if (instruction.getFlowType().isCall()) {
                    for (Address target : instruction.getFlows()) {
                        Function callee = getFunctionAt(target);
                        Map<String,Object> item = new LinkedHashMap<>();
                        item.put("site", instruction.getAddress().toString());
                        item.put("target", target.toString());
                        item.put("flow_override", instruction.getFlowOverride().toString());
                        if (callee != null) { item.put("name", callee.getName()); item.put("no_return", callee.hasNoReturn()); }
                        callees.add(item);
                    }
                }
            }
            if (!returns.isEmpty()) {
                Map<String,Object> row = new LinkedHashMap<>();
                row.put("entry", function.getEntryPoint().toString()); row.put("name", function.getName());
                row.put("signature_source", function.getSignatureSource().toString());
                row.put("body", function.getBody().toString()); row.put("raw_jr_ra_sites", returns);
                row.put("direct_callees", callees); row.put("reachable_return_proven", false);
                candidates.add(row);
            }
        }
        Map<String,Object> result = new LinkedHashMap<>();
        result.put("input_sha256", currentProgram.getExecutableSHA256());
        result.put("internal_functions", functions); result.put("no_return_functions", noReturn);
        result.put("no_return_with_raw_jr_ra_candidates", candidates);
        result.put("printk_named_functions", logging);
        result.put("program_modified_by_script", false);
        Files.writeString(output, new Gson().toJson(result));
        println("No-return functions=" + noReturn + " raw JR RA candidates=" + candidates.size());
    }
}
