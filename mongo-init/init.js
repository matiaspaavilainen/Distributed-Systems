db = db.getSiblingDB('SAND');
db.users.insertMany([
    { name: "John Doe", email: "john@gmail.com" },
    { name: "Jane Doe", email: "jane@gmail.com" },
    { name: "Test Test", email: "test@gmail.com" },
    { name: "Jake Doe", email: "jake@gmail.com" },
    { name: "Jenny Doe", email: "jenny@gmail.com" }
]);