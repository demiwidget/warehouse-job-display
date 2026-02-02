CREATE TABLE `area_job_mappings` (
	`id` int AUTO_INCREMENT NOT NULL,
	`areaId` int NOT NULL,
	`currentRmsJobId` varchar(255) NOT NULL,
	`currentRmsJobNumber` varchar(255) NOT NULL,
	`isActive` int NOT NULL DEFAULT 1,
	`sortOrder` int NOT NULL DEFAULT 0,
	`createdAt` timestamp NOT NULL DEFAULT (now()),
	`updatedAt` timestamp NOT NULL DEFAULT (now()) ON UPDATE CURRENT_TIMESTAMP,
	CONSTRAINT `area_job_mappings_id` PRIMARY KEY(`id`)
);
--> statement-breakpoint
CREATE TABLE `display_settings` (
	`id` int AUTO_INCREMENT NOT NULL,
	`areaId` int NOT NULL,
	`refreshIntervalSeconds` int NOT NULL DEFAULT 30,
	`theme` enum('light','dark') NOT NULL DEFAULT 'dark',
	`showLoadTime` int NOT NULL DEFAULT 1,
	`showJobNumber` int NOT NULL DEFAULT 1,
	`showJobTitle` int NOT NULL DEFAULT 1,
	`fontSize` enum('small','medium','large','xlarge') NOT NULL DEFAULT 'xlarge',
	`createdAt` timestamp NOT NULL DEFAULT (now()),
	`updatedAt` timestamp NOT NULL DEFAULT (now()) ON UPDATE CURRENT_TIMESTAMP,
	CONSTRAINT `display_settings_id` PRIMARY KEY(`id`),
	CONSTRAINT `display_settings_areaId_unique` UNIQUE(`areaId`)
);
--> statement-breakpoint
CREATE TABLE `job_cache` (
	`id` int AUTO_INCREMENT NOT NULL,
	`currentRmsJobId` varchar(255) NOT NULL,
	`jobNumber` varchar(255) NOT NULL,
	`jobTitle` text,
	`loadDate` timestamp,
	`loadTime` varchar(50),
	`status` varchar(100),
	`rawData` text,
	`lastFetched` timestamp NOT NULL DEFAULT (now()),
	`expiresAt` timestamp,
	`createdAt` timestamp NOT NULL DEFAULT (now()),
	`updatedAt` timestamp NOT NULL DEFAULT (now()) ON UPDATE CURRENT_TIMESTAMP,
	CONSTRAINT `job_cache_id` PRIMARY KEY(`id`),
	CONSTRAINT `job_cache_currentRmsJobId_unique` UNIQUE(`currentRmsJobId`)
);
--> statement-breakpoint
CREATE TABLE `warehouse_areas` (
	`id` int AUTO_INCREMENT NOT NULL,
	`name` varchar(255) NOT NULL,
	`description` text,
	`displayName` varchar(255) NOT NULL,
	`isActive` int NOT NULL DEFAULT 1,
	`createdAt` timestamp NOT NULL DEFAULT (now()),
	`updatedAt` timestamp NOT NULL DEFAULT (now()) ON UPDATE CURRENT_TIMESTAMP,
	CONSTRAINT `warehouse_areas_id` PRIMARY KEY(`id`)
);
