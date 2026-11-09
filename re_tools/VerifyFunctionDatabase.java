// Verify a saved analysis database against an original export, in read-only mode.
// @category Firmware
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;

public class VerifyFunctionDatabase extends GhidraScript {
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 2) throw new IllegalArgumentException("Supply original summary and new private verification file");
        Path summaryPath = Path.of(args[0]).toRealPath();
        Path indexPath = summaryPath.getParent().resolve("functions.jsonl");
        Path requested = Path.of(args[1]).toAbsolutePath().normalize();
        Path output = requested.getParent().toRealPath().resolve(requested.getFileName());
        for (Path p = output; p != null; p = p.getParent())
            if (Files.exists(p.resolve(".git"))) throw new IllegalArgumentException("Output must be outside Git");
        if (Files.exists(output)) throw new IllegalArgumentException("Verification output already exists");
        JsonObject original = JsonParser.parseString(Files.readString(summaryPath)).getAsJsonObject();
        String digest = currentProgram.getExecutableSHA256();
        if (!digest.equalsIgnoreCase(original.get("input_sha256").getAsString()))
            throw new IllegalArgumentException("Program digest differs from original export");
        Set<String> expected = new HashSet<>(), actual = new HashSet<>();
        for (String line : Files.readAllLines(indexPath))
            if (!expected.add(JsonParser.parseString(line).getAsJsonObject().get("address").getAsString()))
                throw new IllegalArgumentException("Duplicate original entry");
        FunctionIterator iterator = currentProgram.getFunctionManager().getFunctions(true);
        while (iterator.hasNext()) {
            monitor.checkCancelled();
            Function function = iterator.next();
            if (!function.isExternal()) actual.add(function.getEntryPoint().toString());
        }
        Set<String> missing = new HashSet<>(expected), added = new HashSet<>(actual);
        missing.removeAll(actual); added.removeAll(expected);
        Map<String,Object> result = new LinkedHashMap<>();
        result.put("input_sha256", digest);
        result.put("original_index_sha256", HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(indexPath))));
        result.put("expected_functions", expected.size());
        result.put("actual_functions", actual.size());
        result.put("missing_entries", missing);
        result.put("additional_entries", added);
        result.put("entries_unchanged", expected.equals(actual));
        result.put("target_code_executed", false);
        Files.writeString(output, new Gson().toJson(result));
        println("Verified original entries unchanged=" + expected.equals(actual) + " count=" + actual.size());
        if (!expected.equals(actual)) throw new IllegalStateException("Saved database function entries differ");
    }
}
