// Repair a verified analysis-only false no-return classification in a PRIVATE copy.
// Never alters firmware bytes. Original projects/exports should be retained.
// @category Firmware
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.listing.Bookmark;
import ghidra.program.model.listing.FlowOverride;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.Program;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import com.google.gson.Gson;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

public class RepairKernelPrintkFlow extends GhidraScript {
    private static final String HASH = "9ccc2e7356de88658bbd1c905035695fc032f4784e697ec28cc3cc5c2cd4fb7a";

    private Map<String,Boolean> returnFlags() {
        Map<String,Boolean> result = new LinkedHashMap<>();
        FunctionIterator functions = currentProgram.getFunctionManager().getFunctions(true);
        while (functions.hasNext()) {
            Function function = functions.next();
            result.put(function.getEntryPoint().toString(), function.hasNoReturn());
        }
        return result;
    }

    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 1) throw new IllegalArgumentException("Supply one new private output directory");
        if (!HASH.equalsIgnoreCase(currentProgram.getExecutableSHA256()) ||
            !"MIPS:LE:32:default".equals(currentProgram.getLanguageID().toString()))
            throw new IllegalArgumentException("Verified kernel identity/language required");
        Path out = Path.of(args[0]).toAbsolutePath().normalize();
        if (Files.exists(out)) throw new IllegalArgumentException("Use a new evidence directory");
        Path parent = out.getParent().toRealPath();
        for (Path p = parent; p != null; p = p.getParent())
            if (Files.exists(p.resolve(".git"))) throw new IllegalArgumentException("Output must be outside Git");
        Files.createDirectory(out);
        Address printkAddress = toAddr(0x81526314L);
        Address vprintkAddress = toAddr(0x8102e9a8L);
        Function printk = getFunctionAt(printkAddress);
        Function panic = getFunctionAt(toAddr(0x81526118L));
        if (printk == null || panic == null ||
            currentProgram.getMemory().getInt(toAddr(0x81526350L)) != 0x03e00008 ||
            currentProgram.getMemory().getInt(toAddr(0x8102e9d0L)) != 0x03e00008 ||
            currentProgram.getMemory().getInt(toAddr(0x813f4c38L)) != 0x084fd2fb)
            throw new IllegalStateException("Expected functions/return/continuation bytes do not match");

        Map<String,Object> result = new LinkedHashMap<>();
        result.put("input_sha256", HASH);
        result.put("firmware_bytes_modified", false);
        result.put("printk_no_return_before", printk.hasNoReturn());
        boolean panicBefore = panic.hasNoReturn();
        Map<String,Boolean> beforeFlags = returnFlags();
        List<Address> calls = new ArrayList<>();
        Set<Address> callerEntries = new LinkedHashSet<>();
        ReferenceIterator references = currentProgram.getReferenceManager().getReferencesTo(printkAddress);
        while (references.hasNext()) {
            Reference reference = references.next();
            if (!reference.getReferenceType().isCall()) continue;
            Instruction instruction = getInstructionAt(reference.getFromAddress());
            if (instruction == null) continue;
            calls.add(instruction.getAddress());
            Function caller = getFunctionContaining(instruction.getAddress());
            if (caller != null) callerEntries.add(caller.getEntryPoint());
        }

        currentProgram.getOptions(Program.ANALYSIS_PROPERTIES).setBoolean("Non-Returning Functions - Discovered", false);
        printk.setNoReturn(false);
        int cleared = 0, tailCalls = 0;
        AddressSet starts = new AddressSet();
        List<String> unexpectedOverrides = new ArrayList<>();
        for (Address address : calls) {
            Instruction instruction = getInstructionAt(address);
            int opcode = currentProgram.getMemory().getInt(address) >>> 26;
            if (opcode == 2) {
                // MIPS J is a genuine tail call. CALL_RETURN is correct here;
                // it must not be confused with a false no-return JAL override.
                tailCalls++;
                continue;
            }
            if (opcode != 3) {
                unexpectedOverrides.add(address.toString() + ":unhandled-raw-opcode-" + opcode);
                continue;
            }
            if (instruction.getFlowOverride() == FlowOverride.CALL_RETURN) {
                instruction.setFlowOverride(FlowOverride.NONE);
                cleared++;
            } else if (instruction.getFlowOverride() != FlowOverride.NONE) {
                unexpectedOverrides.add(address.toString() + ":" + instruction.getFlowOverride());
            }
            if (instruction.getFallThrough() != null) starts.add(instruction.getFallThrough());
        }
        starts.add(vprintkAddress);
        AddressSet text = new AddressSet();
        text.addRange(toAddr(0x81001400L), toAddr(0x8152cf9fL));
        text.addRange(toAddr(0x81734000L), toAddr(0x81758ca3L));
        text.addRange(toAddr(0x81760c80L), toAddr(0x81761fffL));
        DisassembleCommand disassembly = new DisassembleCommand(starts, text, true);
        disassembly.enableCodeAnalysis(false);
        boolean disassemblyResult = disassembly.applyTo(currentProgram, monitor);
        int fixupSuccess = 0, changedBodies = 0;
        List<String> changedEntries = new ArrayList<>();
        for (Address entry : callerEntries) {
            monitor.checkCancelled();
            Function function = getFunctionAt(entry);
            if (function == null) continue;
            AddressSet originalBody = new AddressSet(function.getBody());
            if (CreateFunctionCmd.fixupFunctionBody(currentProgram, function, monitor)) fixupSuccess++;
            if (!originalBody.equals(function.getBody())) {
                changedBodies++;
                changedEntries.add(entry.toString());
            }
        }
        Function vprintk = getFunctionAt(vprintkAddress);
        boolean vprintkCreated = vprintk == null;
        if (vprintk == null) vprintk = createFunction(vprintkAddress, "vprintk");
        for (Bookmark bookmark : currentProgram.getBookmarkManager().getBookmarks(printkAddress)) {
            if (bookmark.getTypeString().equals("Analysis") &&
                bookmark.getCategory().equals("Non-Returning Function") &&
                bookmark.getComment().equals("Non-Returning Function Found"))
                currentProgram.getBookmarkManager().removeBookmark(bookmark);
        }

        int fallthrough = 0, continuationDecoded = 0, remainingCallReturn = 0, tailCallsPreserved = 0;
        List<String> unresolvedCalls = new ArrayList<>();
        for (Address address : calls) {
            Instruction instruction = getInstructionAt(address);
            int opcode = currentProgram.getMemory().getInt(address) >>> 26;
            if (opcode == 2) {
                if (instruction.getFlowOverride() == FlowOverride.CALL_RETURN) tailCallsPreserved++;
                else unresolvedCalls.add(address.toString() + ":tail-call-override-changed");
                continue;
            }
            if (instruction.getFlowOverride() == FlowOverride.CALL_RETURN) remainingCallReturn++;
            Address next = instruction.getFallThrough();
            if (next != null) {
                fallthrough++;
                if (getInstructionAt(next) != null) continuationDecoded++;
                else unresolvedCalls.add(address.toString() + ":continuation-not-decoded");
            } else unresolvedCalls.add(address.toString() + ":no-fallthrough");
        }
        Map<String,Boolean> afterFlags = returnFlags();
        List<String> otherFlagChanges = new ArrayList<>();
        for (Map.Entry<String,Boolean> entry : beforeFlags.entrySet()) {
            if (!entry.getKey().equals(printkAddress.toString()) &&
                !entry.getValue().equals(afterFlags.get(entry.getKey()))) otherFlagChanges.add(entry.getKey());
        }
        Function example = getFunctionAt(toAddr(0x813f4ba0L));
        boolean exampleFixed = example != null && example.getBody().contains(toAddr(0x813f4c38L)) &&
                               example.getBody().contains(toAddr(0x813f4c3cL));
        result.put("printk_no_return_after", printk.hasNoReturn());
        result.put("printk_callsite_count", calls.size());
        result.put("raw_j_tail_calls", tailCalls);
        result.put("tail_call_return_overrides_preserved", tailCallsPreserved);
        result.put("raw_jal_ordinary_calls", calls.size() - tailCalls - unexpectedOverrides.size());
        result.put("call_return_overrides_cleared", cleared);
        result.put("ordinary_call_return_overrides_remaining", remainingCallReturn);
        result.put("calls_with_fallthrough", fallthrough);
        result.put("calls_with_decoded_continuation", continuationDecoded);
        result.put("unresolved_calls", unresolvedCalls);
        result.put("unexpected_overrides_untouched", unexpectedOverrides);
        result.put("caller_functions_considered", callerEntries.size());
        result.put("body_fixup_reported_success", fixupSuccess);
        result.put("caller_bodies_changed", changedBodies);
        result.put("changed_caller_entries", changedEntries);
        result.put("vprintk_created", vprintkCreated && vprintk != null);
        result.put("vprintk_no_return", vprintk == null ? null : vprintk.hasNoReturn());
        result.put("vprintk_body", vprintk == null ? null : vprintk.getBody().toString());
        result.put("example_body_has_jump_and_delay_slot", exampleFixed);
        result.put("example_body", example == null ? null : example.getBody().toString());
        result.put("panic_no_return_before", panicBefore);
        result.put("panic_no_return_after", panic.hasNoReturn());
        result.put("other_existing_no_return_flags_changed", otherFlagChanges);
        result.put("disassembly_command_result", disassemblyResult);
        result.put("disassembly_status", disassembly.getStatusMsg());
        result.put("disabled_analyzer", "Non-Returning Functions - Discovered");
        result.put("full_autoanalysis_run", false);
        result.put("all_machine_code_proven_covered", false);
        DecompInterface decompiler = new DecompInterface();
        try {
            if (decompiler.openProgram(currentProgram) && example != null) {
                DecompileResults decompiled = decompiler.decompileFunction(example, 30, monitor);
                boolean success = decompiled.decompileCompleted() && decompiled.getDecompiledFunction() != null;
                result.put("example_decompiled", success);
                result.put("example_decompile_error", decompiled.getErrorMessage());
                if (success) Files.writeString(out.resolve("MT_ATERDDParseResult.c"), decompiled.getDecompiledFunction().getC());
            }
        } finally { decompiler.dispose(); }
        Files.writeString(out.resolve("repair-summary.json"), new Gson().toJson(result));
        println("printk call overrides cleared=" + cleared + " fallthrough=" + fallthrough +
                " bodies changed=" + changedBodies + " example fixed=" + exampleFixed);
        if (panic.hasNoReturn() != panicBefore || !otherFlagChanges.isEmpty())
            throw new IllegalStateException("Unexpected return metadata change; inspect private evidence");
    }
}
