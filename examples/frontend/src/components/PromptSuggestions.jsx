export default function PromptSuggestions({ onSelect }) {
    const suggestions = [
    "I want to open a bank account",
    "Check account balance",
    "Request a credit card",
    "Check credit card limit",
    ];

    return (
        <div className="flex flex-col items-center justify-center h-full text-gray-400 gap-4">
            <h2 className="text-xl font-medium text-white">How can I help you today?</h2>
            <div className="grid grid-cols-2 gap-3">
                {suggestions.map((s, i) => (
                <button
                    key={i}
                    onClick={() => onSelect(s)}
                    className="bg-gray-800 px-4 py-2 rounded-xl hover:bg-gray-700 text-sm text-gray-200"
                >{s}
                </button>
            ))}
            </div>
        </div>
    );
}