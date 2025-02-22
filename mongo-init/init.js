// COPY THIS TO THE CONFIGMAP IF CHANGED

// Only initialize if this is mongodb-0 (control plane)
if (hostname().endsWith('-0')) {
    // ...existing initialization code...
} else {
    print("Not control plane instance, skipping initialization");
}

// First, create the database
db = db.getSiblingDB('SAND');

// Function to generate random date within a range
function randomDate(start, end) {
    return new Date(start.getTime() + Math.random() * (end.getTime() - start.getTime()));
}

// Generate 10000 users with realistic data
let users = [];
for (let i = 0; i < 10000; i++) {
    const firstName = ['John', 'Jane', 'Mike', 'Sarah', 'David', 'Emma', 'James', 'Emily'][Math.floor(Math.random() * 8)];
    const lastName = ['Smith', 'Johnson', 'Williams', 'Brown', 'Jones', 'Garcia', 'Miller', 'Davis'][Math.floor(Math.random() * 8)];

    users.push({
        name: `${firstName} ${lastName}`,
        email: `${firstName.toLowerCase()}.${lastName.toLowerCase()}.${i}@example.com`, // Added index to ensure uniqueness
        age: Math.floor(Math.random() * 50) + 18,
        address: {
            street: `${Math.floor(Math.random() * 9999) + 1} ${['Main', 'Oak', 'Maple', 'Cedar', 'Pine'][Math.floor(Math.random() * 5)]} St`,
            city: ['New York', 'Los Angeles', 'Chicago', 'Houston', 'Phoenix', 'Philadelphia'][Math.floor(Math.random() * 6)],
            state: ['NY', 'CA', 'IL', 'TX', 'AZ', 'PA'][Math.floor(Math.random() * 6)],
            zipCode: Math.floor(Math.random() * 89999) + 10000
        },
        created_at: randomDate(new Date(2020, 0, 1), new Date()),
        orders: Math.floor(Math.random() * 50),
        status: ['active', 'inactive', 'suspended'][Math.floor(Math.random() * 3)],
        premium: Math.random() < 0.2
    });
}

// Insert users in batches to avoid memory issues
const batchSize = 1000;
for (let i = 0; i < users.length; i += batchSize) {
    db.users.insertMany(users.slice(i, i + batchSize));
}

// Create indexes for common queries
db.users.createIndex({ "email": 1 }, { unique: true });
db.users.createIndex({ "status": 1 });
db.users.createIndex({ "created_at": 1 });
db.users.createIndex({ "orders": -1 });

print("Initialized database with " + users.length + " users");