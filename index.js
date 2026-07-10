const fs = require('fs');
const path = require('path');

// Function to escape HTML special characters
function escapeHtml(unsafe) {
    return unsafe
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/\""/g, "&quot;")
        .replace(/\'/g, "&#039;");
}

// Function to render timeline events
function render(events) {
    return events.map(event => {
        const date = new Date(event.date);
        const formattedDate = date.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' });
        return `
            <div class="event">
                <h3>${escapeHtml(event.title)}</h3>
                <p><strong>日期:</strong> ${formattedDate} (北京时间)</p>
                <p><strong>地点:</strong> ${escapeHtml(event.location)}</p>
                <p>${escapeHtml(event.description)}</p>
            </div>
        `;
    }).join('\n');
}

// Sample timeline data
const timelineData = [
    {
        title: "事件1",
        date: "2023-10-01T00:00:00Z",
        location: "地点1",
        description: "事件1的描述"
    },
    {
        title: "事件2",
        date: "2023-10-02T00:00:00Z",
        location: "地点2",
        description: "事件2的描述"
    }
];

// Generate HTML content
const htmlContent = `
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>时间线</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .event { margin-bottom: 20px; padding: 10px; border: 1px solid #ddd; border-radius: 5px; }
        h3 { margin-top: 0; }
    </style>
</head>
<body>
    <h1>时间线</h1>
    ${render(timelineData)}
</body>
</html>
`;

// Write HTML to file
const outputPath = path.join(__dirname, 'timeline.html');
fs.writeFileSync(outputPath, htmlContent);

console.log(`Timeline generated at ${outputPath}`);